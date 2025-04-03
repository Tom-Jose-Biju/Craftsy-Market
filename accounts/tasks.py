from celery import shared_task
from django.core.management import call_command
from .models import Delivery, DeliveryPartner, DeliveryStatusHistory
from .utils import assign_optimal_delivery_partner, optimize_delivery_route, calculate_eta
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.utils import timezone
from datetime import timedelta
from .models import Notification
import logging

logger = logging.getLogger(__name__)

@shared_task
def optimize_delivery_routes():
    """Optimize routes for all active delivery partners."""
    call_command('optimize_routes')

@shared_task
def assign_delivery_partners():
    """Assign delivery partners to pending deliveries."""
    from .models import Delivery, DeliveryPartner, DeliveryStatusHistory
    from .utils import assign_optimal_delivery_partner
    
    # Get all pending deliveries without partners
    pending_deliveries = Delivery.objects.filter(
        status='pending',
        delivery_partner__isnull=True
    ).select_related('order')

    for delivery in pending_deliveries:
        try:
            # Find optimal partner using our utility function
            partner = assign_optimal_delivery_partner(delivery)
            
            if partner:
                # Update delivery with assigned partner
                delivery.delivery_partner = partner
                delivery.status = 'assigned'
                delivery.save()
                
                # Create status history record
                DeliveryStatusHistory.objects.create(
                    delivery=delivery,
                    status='assigned',
                    notes=f'Assigned to delivery partner {partner.user.get_full_name()}'
                )
                
                # Send notifications
                channel_layer = get_channel_layer()
                
                # Notify the delivery partner
                Notification.objects.create(
                    user=partner.user,
                    title='New Delivery Assignment',
                    message=f'You have been assigned delivery #{delivery.id}',
                )
                
                # Update WebSocket clients
                async_to_sync(channel_layer.group_send)(
                    f'delivery_{delivery.id}',
                    {
                        'type': 'status_update',
                        'status': 'assigned',
                        'partner_name': partner.user.get_full_name(),
                        'partner_phone': partner.phone_number,
                        'estimated_pickup': timezone.now().isoformat(),
                        'estimated_delivery': (timezone.now() + timedelta(hours=2)).isoformat()
                    }
                )
                
                # Update partner's availability
                partner.is_available = False
                partner.save()
            
            else:
                # No suitable partner found, log this
                logger.warning(f"No suitable delivery partner found for delivery {delivery.id}")
                
        except Exception as e:
            logger.error(f"Error assigning delivery partner for delivery {delivery.id}: {str(e)}")
            continue

@shared_task
def update_delivery_eta():
    """Update estimated delivery times for active deliveries."""
    from .models import Delivery
    from .utils import calculate_eta
    
    active_deliveries = Delivery.objects.filter(
        status__in=['picked_up', 'in_transit', 'out_for_delivery']
    ).select_related('delivery_partner')

    channel_layer = get_channel_layer()
    
    for delivery in active_deliveries:
        try:
            if delivery.delivery_partner and delivery.delivery_partner.current_location_lat:
                # Calculate new ETA based on current location and traffic
                new_eta = calculate_eta(
                    float(delivery.delivery_partner.current_location_lat),
                    float(delivery.delivery_partner.current_location_lng),
                    float(delivery.destination_lat),
                    float(delivery.destination_lng)
                )
                
                # Update delivery ETA
                delivery.expected_delivery_time = new_eta
                delivery.save()
                
                # Send WebSocket update
                async_to_sync(channel_layer.group_send)(
                    f'delivery_{delivery.id}',
                    {
                        'type': 'eta_update',
                        'eta': new_eta.isoformat(),
                        'current_location': {
                            'lat': delivery.delivery_partner.current_location_lat,
                            'lng': delivery.delivery_partner.current_location_lng
                        }
                    }
                )
        except Exception as e:
            logger.error(f"Error updating ETA for delivery {delivery.id}: {str(e)}")
            continue
