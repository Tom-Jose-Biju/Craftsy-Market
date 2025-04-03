import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from django.core import logger
from .models import Delivery, DeliveryRoute, DeliveryStatusHistory, Notification

class DeliveryTrackingConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.delivery_id = self.scope['url_route']['kwargs']['delivery_id']
        self.room_group_name = f'delivery_{self.delivery_id}'
        
        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        
        await self.accept()
        
        # Send initial delivery data
        try:
            delivery_data = await self.get_delivery_data()
            await self.send(text_data=json.dumps({
                'type': 'delivery_data',
                'delivery': delivery_data
            }))
        except ObjectDoesNotExist:
            await self.close()

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'location_update':
                # Validate location data
                latitude = float(data.get('latitude', 0))
                longitude = float(data.get('longitude', 0))
                
                if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
                    raise ValueError("Invalid coordinates")
                
                # Save location update
                await self.save_location_update(latitude, longitude)
                
                # Broadcast location update to group
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'location_update',
                        'latitude': latitude,
                        'longitude': longitude,
                        'timestamp': timezone.now().isoformat()
                    }
                )
            
            elif message_type == 'status_update':
                # Validate status
                status = data.get('status')
                if status not in ['pending', 'assigned', 'picked_up', 'in_transit', 'delivered', 'cancelled']:
                    raise ValueError("Invalid status")
                
                # Save status update
                await self.save_status_update(status, data.get('notes', ''))
                
                # Broadcast status update
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'status_update',
                        'status': status,
                        'notes': data.get('notes', ''),
                        'timestamp': timezone.now().isoformat()
                    }
                )
                
        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))
        except ValueError as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': str(e)
            }))
        except Exception as e:
            logger.error(f"Error in DeliveryTrackingConsumer.receive: {str(e)}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Internal server error'
            }))

    async def location_update(self, event):
        """Handle location updates."""
        await self.send(text_data=json.dumps({
            'type': 'location_update',
            'latitude': event['latitude'],
            'longitude': event['longitude'],
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))

    async def status_update(self, event):
        """Handle status updates."""
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'status': event['status'],
            'notes': event.get('notes', ''),
            'timestamp': event.get('timestamp', timezone.now().isoformat())
        }))

    async def eta_update(self, event):
        """Handle ETA updates."""
        await self.send(text_data=json.dumps({
            'type': 'eta_update',
            'eta': event['eta'],
            'current_location': event.get('current_location', {}),
            'timestamp': timezone.now().isoformat()
        }))

    @database_sync_to_async
    def get_delivery_data(self):
        delivery = Delivery.objects.select_related(
            'delivery_partner__user',
            'order__user'
        ).get(id=self.delivery_id)
        
        # Get last 10 status updates
        status_history = DeliveryStatusHistory.objects.filter(
            delivery=delivery
        ).order_by('-timestamp')[:10]
        
        # Get last known location
        last_location = DeliveryRoute.objects.filter(
            delivery=delivery
        ).order_by('-timestamp').first()
        
        return {
            'id': delivery.id,
            'status': delivery.status,
            'delivery_partner': {
                'name': delivery.delivery_partner.user.get_full_name(),
                'phone': delivery.delivery_partner.phone_number
            } if delivery.delivery_partner else None,
            'current_location': {
                'latitude': float(last_location.latitude),
                'longitude': float(last_location.longitude)
            } if last_location else None,
            'status_history': [{
                'status': status.status,
                'notes': status.notes,
                'location': status.location,
                'timestamp': status.timestamp.isoformat()
            } for status in status_history]
        }

    @database_sync_to_async
    def save_location_update(self, latitude, longitude):
        delivery = Delivery.objects.get(id=self.delivery_id)
        DeliveryRoute.objects.create(
            delivery=delivery,
            latitude=latitude,
            longitude=longitude
        )
        
        # Update delivery partner's current location
        if delivery.delivery_partner:
            delivery.delivery_partner.current_location_lat = latitude
            delivery.delivery_partner.current_location_lng = longitude
            delivery.delivery_partner.last_location_update = timezone.now()
            delivery.delivery_partner.save()

    @database_sync_to_async
    def save_status_update(self, status, notes):
        delivery = Delivery.objects.get(id=self.delivery_id)
        delivery.status = status
        delivery.save()
        
        # Create status history record
        DeliveryStatusHistory.objects.create(
            delivery=delivery,
            status=status,
            notes=notes
        )
        
        # Create notification for the customer
        Notification.objects.create(
            user=delivery.order.user,
            title='Delivery Status Update',
            message=f'Your delivery #{delivery.id} is now {status}',
        )
