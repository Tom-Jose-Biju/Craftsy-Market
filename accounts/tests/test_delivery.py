from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import (
    Delivery, DeliveryPartner, DeliveryStatusHistory,
    DeliveryRoute, Order, User
)
from django.utils import timezone
from decimal import Decimal
import json

class DeliveryTestCase(TestCase):
    def setUp(self):
        # Create test users
        self.customer = get_user_model().objects.create_user(
            username='testcustomer',
            email='customer@test.com',
            password='testpass123'
        )
        
        self.delivery_partner_user = get_user_model().objects.create_user(
            username='testpartner',
            email='partner@test.com',
            password='testpass123'
        )
        
        # Create delivery partner
        self.delivery_partner = DeliveryPartner.objects.create(
            user=self.delivery_partner_user,
            phone_number='1234567890',
            vehicle_type='bike',
            is_available=True
        )
        
        # Create test order with correct field names
        self.order = Order.objects.create(
            user=self.customer,
            total_price=Decimal('100.00'),
            status='processing',
            tracking_number='TEST123'
        )
        
        # Create test delivery
        self.delivery = Delivery.objects.create(
            order=self.order,
            delivery_partner=self.delivery_partner,
            status='pending',
            delivery_address='123 Test St',
            destination_lat='12.9716',
            destination_lng='77.5946',
            expected_delivery_time=timezone.now() + timezone.timedelta(days=1)
        )
        
        self.client = Client()
    
    def test_delivery_creation(self):
        """Test that delivery is created correctly"""
        self.assertEqual(self.delivery.status, 'pending')
        self.assertEqual(self.delivery.delivery_address, '123 Test St')
        self.assertEqual(self.delivery.order, self.order)
        self.assertEqual(self.delivery.delivery_partner, self.delivery_partner)
    
    def test_delivery_status_update(self):
        """Test delivery status updates"""
        # Login as delivery partner
        self.client.login(username='testpartner', password='testpass123')
        
        # Update status to in_transit
        response = self.client.post(
            reverse('update_delivery_status', args=[self.delivery.id]),
            data=json.dumps({
                'status': 'in_transit',
                'notes': 'On the way',
                'location': '123 Test St'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        
        # Verify status is updated
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'in_transit')
        
        # Verify status history is created
        status_history = DeliveryStatusHistory.objects.filter(delivery=self.delivery)
        self.assertEqual(status_history.count(), 1)
        self.assertEqual(status_history.first().status, 'in_transit')

    def test_delivery_location_update(self):
        """Test delivery location updates"""
        # Login as delivery partner
        self.client.login(username='testpartner', password='testpass123')
        
        # Update location
        response = self.client.post(
            reverse('update_delivery_location', args=[self.delivery.id]),
            data=json.dumps({
                'latitude': '12.9716',
                'longitude': '77.5946'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        
        # Verify route is created
        route = DeliveryRoute.objects.filter(delivery=self.delivery)
        self.assertEqual(route.count(), 1)
        self.assertEqual(float(route.first().latitude), float('12.9716'))
        self.assertEqual(float(route.first().longitude), float('77.5946'))
        
        # Verify delivery partner location is updated
        self.delivery_partner.refresh_from_db()
        self.assertEqual(float(self.delivery_partner.current_location_lat), float('12.9716'))
        self.assertEqual(float(self.delivery_partner.current_location_lng), float('77.5946'))
    
    def test_delivery_completion(self):
        """Test delivery completion process"""
        # Login as delivery partner
        self.client.login(username='testpartner', password='testpass123')
        
        # Mark delivery as delivered
        response = self.client.post(
            reverse('update_delivery_status', args=[self.delivery.id]),
            data=json.dumps({
                'status': 'delivered',
                'notes': 'Delivered successfully',
                'location': '123 Test St'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        
        # Verify delivery status
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'delivered')
        self.assertIsNotNone(self.delivery.actual_delivery_time)
        
        # Verify order status
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'delivered')

    def test_invalid_status_update(self):
        """Test invalid status updates are rejected"""
        # Login as delivery partner
        self.client.login(username='testpartner', password='testpass123')
        
        # Try to update with invalid status
        response = self.client.post(
            reverse('update_delivery_status', args=[self.delivery.id]),
            data=json.dumps({
                'status': 'invalid_status',
                'notes': 'Test'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        
        # Verify status didn't change
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'pending')

    def test_unauthorized_access(self):
        """Test unauthorized users cannot update delivery"""
        # Login as customer (not delivery partner)
        self.client.login(username='testcustomer', password='testpass123')
        
        # Try to update status
        response = self.client.post(
            reverse('update_delivery_status', args=[self.delivery.id]),
            data=json.dumps({
                'status': 'picked_up',
                'notes': 'Test'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 403)
        
        # Verify status didn't change
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'pending')
