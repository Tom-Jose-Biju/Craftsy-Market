from django.core.management.base import BaseCommand
from django.utils import timezone
from accounts.models import DeliveryPartner
from accounts.utils import optimize_delivery_route

class Command(BaseCommand):
    help = 'Optimize delivery routes for all active delivery partners'

    def handle(self, *args, **kwargs):
        # Get all active delivery partners with pending deliveries
        active_partners = DeliveryPartner.objects.filter(
            is_available=True,
            status='approved'
        ).exclude(
            current_location_lat__isnull=True,
            current_location_lng__isnull=True
        )

        for partner in active_partners:
            try:
                # Get optimized route
                optimized_route = optimize_delivery_route(partner)
                
                if optimized_route:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Optimized route for partner {partner.user.get_full_name()}:'
                        )
                    )
                    
                    for i, delivery in enumerate(optimized_route, 1):
                        self.stdout.write(
                            f'{i}. Delivery #{delivery.id} - {delivery.delivery_address}'
                        )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f'No pending deliveries for partner {partner.user.get_full_name()}'
                        )
                    )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Error optimizing route for partner {partner.user.get_full_name()}: {str(e)}'
                    )
                )
