import json
import requests
from django.conf import settings
from django.db import models
from django.utils import timezone
from math import radians, sin, cos, sqrt, atan2
from typing import List, Tuple, Dict
from .models import Delivery, DeliveryPartner, DeliveryEarning
from functools import lru_cache
from transformers import AutoProcessor, AutoModelForImageClassification
import torch
import logging

logger = logging.getLogger(__name__)

def is_delivery_partner(user) -> bool:
    """Check if a user is a delivery partner."""
    if not user or not user.is_authenticated:
        return False
    return (
        user.user_type == 'delivery_partner' and 
        hasattr(user, 'delivery_partner') and 
        user.delivery_partner.status == 'approved'
    )

def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the distance between two points using the Haversine formula."""
    R = 6371  # Earth's radius in kilometers

    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    distance = R * c

    return distance

def get_optimal_route(origin: Tuple[float, float], destinations: List[Tuple[float, float]]) -> List[int]:
    """Get optimal route using Google Maps Distance Matrix API."""
    if not destinations:
        return []

    # Build the API request URL
    base_url = "https://maps.googleapis.com/maps/api/distancematrix/json?"
    origin_str = f"{origin[0]},{origin[1]}"
    destinations_str = "|".join([f"{lat},{lng}" for lat, lng in destinations])
    
    params = {
        'origins': origin_str,
        'destinations': destinations_str,
        'key': settings.GOOGLE_MAPS_API_KEY
    }

    try:
        response = requests.get(base_url, params=params)
        data = response.json()

        if data['status'] != 'OK':
            raise Exception(f"Error from Google Maps API: {data['status']}")

        # Extract distances and create a simple order based on closest points
        distances = []
        for i, row in enumerate(data['rows'][0]['elements']):
            if row['status'] == 'OK':
                distances.append((i, row['distance']['value']))
            else:
                distances.append((i, float('inf')))

        # Sort by distance
        sorted_indices = [i for i, _ in sorted(distances, key=lambda x: x[1])]
        return sorted_indices

    except Exception as e:
        print(f"Error calculating optimal route: {str(e)}")
        # Fallback to simple distance calculation
        distances = []
        for i, dest in enumerate(destinations):
            dist = calculate_distance(origin[0], origin[1], dest[0], dest[1])
            distances.append((i, dist))
        
        sorted_indices = [i for i, _ in sorted(distances, key=lambda x: x[1])]
        return sorted_indices

def assign_optimal_delivery_partner(delivery: Delivery) -> DeliveryPartner:
    """Assign the most suitable delivery partner based on location and workload."""
    delivery_address = delivery.delivery_address
    available_partners = DeliveryPartner.objects.filter(
        is_available=True,
        status='approved'
    ).exclude(
        current_location_lat__isnull=True,
        current_location_lng__isnull=True
    )

    if not available_partners:
        return None

    # Calculate scores for each partner
    partner_scores = []
    for partner in available_partners:
        # Get partner's current deliveries count
        current_deliveries = Delivery.objects.filter(
            delivery_partner=partner,
            status__in=['picked_up', 'in_transit', 'out_for_delivery']
        ).count()

        # Calculate distance from partner to delivery location
        distance = calculate_distance(
            float(partner.current_location_lat),
            float(partner.current_location_lng),
            float(delivery.destination_lat),
            float(delivery.destination_lng)
        )

        # Calculate score (lower is better)
        # Weight factors can be adjusted based on importance
        distance_weight = 0.6
        workload_weight = 0.4
        
        # Normalize distance (assume max reasonable distance is 20km)
        normalized_distance = min(distance / 20.0, 1.0)
        
        # Normalize workload (assume max reasonable deliveries is 5)
        normalized_workload = min(current_deliveries / 5.0, 1.0)
        
        score = (distance_weight * normalized_distance + 
                workload_weight * normalized_workload)
        
        partner_scores.append((partner, score))

    # Sort by score (lower is better) and return best partner
    sorted_partners = sorted(partner_scores, key=lambda x: x[1])
    return sorted_partners[0][0] if sorted_partners else None

def optimize_delivery_route(delivery_partner: DeliveryPartner) -> List[Delivery]:
    """Optimize the route for a delivery partner's pending deliveries."""
    pending_deliveries = Delivery.objects.filter(
        delivery_partner=delivery_partner,
        status__in=['picked_up', 'in_transit']
    )

    if not pending_deliveries:
        return []

    # Get current location and delivery destinations
    origin = (
        float(delivery_partner.current_location_lat),
        float(delivery_partner.current_location_lng)
    )
    
    destinations = [
        (float(d.destination_lat), float(d.destination_lng))
        for d in pending_deliveries
    ]

    # Get optimal route
    optimal_order = get_optimal_route(origin, destinations)
    
    # Return deliveries in optimal order
    return [pending_deliveries[i] for i in optimal_order]

def process_delivery_earnings(request, delivery_id):
    """Process earnings for a completed delivery."""
    try:
        delivery = Delivery.objects.select_related(
            'order', 'delivery_partner'
        ).get(id=delivery_id)
        
        if delivery.status != 'delivered':
            raise ValueError('Cannot process earnings for undelivered order')
            
        if not delivery.delivery_partner:
            raise ValueError('No delivery partner assigned')
            
        # Calculate base earnings
        order_total = delivery.order.total_amount
        base_delivery_fee = 50  # Base delivery fee in rupees
        
        # Calculate distance-based fee
        distance_fee = delivery.distance * 10  # Rs. 10 per km
        
        # Calculate time-based fee (if delivery was faster than expected)
        time_fee = 0
        if delivery.expected_delivery_time and delivery.actual_delivery_time:
            time_saved = delivery.expected_delivery_time - delivery.actual_delivery_time
            if time_saved.total_seconds() > 0:
                time_fee = 20  # Bonus for early delivery
        
        # Calculate total earnings
        total_earnings = base_delivery_fee + distance_fee + time_fee
        
        # Calculate platform fee (20%)
        platform_fee = total_earnings * 0.20
        
        # Calculate delivery partner's share (80%)
        partner_share = total_earnings - platform_fee
        
        # Create earnings record
        DeliveryEarning.objects.create(
            delivery=delivery,
            delivery_partner=delivery.delivery_partner,
            base_fee=base_delivery_fee,
            distance_fee=distance_fee,
            time_bonus=time_fee,
            total_amount=total_earnings,
            platform_fee=platform_fee,
            partner_share=partner_share,
            status='processed'
        )
        
        # Update delivery partner's total earnings
        delivery_partner = delivery.delivery_partner
        delivery_partner.total_earnings = models.F('total_earnings') + partner_share
        delivery_partner.save()
        
        return True
        
    except Delivery.DoesNotExist:
        raise ValueError('Delivery not found')
    except Exception as e:
        logger.error(f'Error processing delivery earnings: {str(e)}')
        raise

@lru_cache(maxsize=1)
def get_image_classifier():
    """
    Get the image classifier model and processor.
    Uses lru_cache to cache the model and processor for better performance.
    
    Returns:
        tuple: A tuple containing (processor, model) for image classification
    """
    model_name = "microsoft/resnet-50"  # Using ResNet-50 pre-trained model
    
    # Load processor and model
    processor = AutoProcessor.from_pretrained(model_name)
    model = AutoModelForImageClassification.from_pretrained(model_name)
    
    # Move model to GPU if available
    if torch.cuda.is_available():
        model = model.cuda()
    
    model.eval()  # Set model to evaluation mode
    return processor, model
