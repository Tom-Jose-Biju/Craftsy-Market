from django.core.management.base import BaseCommand
from tensorflow.keras.applications import EfficientNetB0

class Command(BaseCommand):
    help = 'Downloads EfficientNet-B0 weights'

    def handle(self, *args, **options):
        self.stdout.write('Downloading EfficientNet-B0 weights...')
        EfficientNetB0(weights='imagenet', include_top=True)
        self.stdout.write(self.style.SUCCESS('Successfully downloaded EfficientNet-B0 weights'))