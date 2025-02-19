from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile
# from tensorflow.keras.applications.efficientnet import EfficientNetB0, preprocess_input, decode_predictions
# from tensorflow.keras.preprocessing import image
import numpy as np
# import tensorflow as tf
from django.db.models.signals import post_save
from django.dispatch import receiver
import io
from django.conf import settings

class User(AbstractUser):
    USER_TYPE_CHOICES = (
        ('artisan', 'Artisan'),
        ('customer', 'Customer'),
        ('admin', 'Admin'),
        ('delivery_partner', 'Delivery Partner'),
    )
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, default="customer")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, default='active')
    phone_number = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)

    def __str__(self):
        return self.username

    class Meta:
        db_table = 'auth_user'
        app_label = 'accounts'

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    street_address = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=255, blank=True, null=True)
    state = models.CharField(max_length=255, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=255, blank=True, null=True)
    profile_image = models.ImageField(upload_to='profile_images/', blank=True, null=True)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    status = models.CharField(max_length=20, default='active')

    def __str__(self):
        return self.user.username

class Artisan(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    gst_number = models.CharField(max_length=15, blank=True, null=True)
    gst_certificate = models.FileField(upload_to='gst_certificates/', blank=True, null=True)

    def __str__(self):
        return self.user.username

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE, related_name='subcategories')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)  # Add this line

    def __str__(self):
        return self.name
    
    def get_ancestors(self):
        ancestors = []
        parent = self.parent
        while parent:
            ancestors.append(parent)
            parent = parent.parent
        return ancestors

    class Meta:
        verbose_name_plural = "Categories"

class Product(models.Model):
    CATEGORY_CHOICES = [
        ('jewelry', 'Jewelry'),
        ('pottery', 'Pottery'),
        ('woodworking', 'Woodworking'),
        ('painting', 'Painting'),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='products')
    inventory = models.PositiveIntegerField()
    artisan = models.ForeignKey(Artisan, on_delete=models.CASCADE, related_name='products')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    def is_in_stock(self):
        return self.inventory > 0

    # def classify_image(self, image_file):
    #     print("Loading custom EfficientNet model...")
    #     model = tf.keras.models.load_model('custom_efficientnet_model.h5')
    #     print("Model loaded successfully")

    #     print(f"Image file type: {type(image_file)}")
        
    #     if isinstance(image_file, (InMemoryUploadedFile, TemporaryUploadedFile)):
    #         print("Processing UploadedFile")
    #         img = image.load_img(io.BytesIO(image_file.read()), target_size=(224, 224))
    #     else:
    #         print("Processing file path")
    #         img = image.load_img(image_file, target_size=(224, 224))
        
    #     print("Image loaded successfully")
    #     x = image.img_to_array(img)
    #     x = np.expand_dims(x, axis=0)
    #     x = x / 255.0  # Normalize the image

    #     print("Making prediction...")
    #     preds = model.predict(x)
    #     print("Prediction made successfully")
    #     predicted_class_index = np.argmax(preds[0])
    #     category_names = list(self.CATEGORY_CHOICES)
    #     predicted_category = category_names[predicted_class_index]
    #     print(f"Predicted category: {predicted_category}")

    #     return predicted_category

    @staticmethod
    def map_prediction_to_category(predictions):
        # Define expanded mappings from ImageNet classes to your categories
        category_mappings = {
            'jewelry': [
                'necklace', 'earring', 'ring', 'bangle', 'pendant', 'bracelet', 'anklet',
                'brooch', 'tiara', 'cufflink', 'locket', 'charm', 'gemstone', 'pearl',
                'gold', 'silver', 'platinum', 'diamond', 'ruby', 'sapphire', 'emerald'
            ],
            'pottery': [
                'vase', 'pot', 'ceramic', 'earthenware', 'porcelain', 'bowl', 'plate',
                'mug', 'teapot', 'jug', 'urn', 'planter', 'tile', 'figurine', 'sculpture',
                'clay', 'terracotta', 'stoneware', 'raku', 'glaze', 'kiln'
            ],
            'woodworking': [
                'wooden_spoon', 'chair', 'table', 'cabinet', 'wooden', 'bookshelf',
                'cutting_board', 'bowl', 'box', 'frame', 'carving', 'sculpture',
                'furniture', 'desk', 'bench', 'chest', 'dresser', 'stool', 'hardwood',
                'softwood', 'plywood', 'veneer', 'lathe', 'chisel', 'saw'
            ],
            'painting': [
                'paintbrush', 'canvas', 'acrylic_paint', 'oil_paint', 'watercolor',
                'palette', 'easel', 'art', 'artwork', 'portrait', 'landscape', 'still_life',
                'abstract', 'mural', 'fresco', 'gouache', 'tempera', 'pastel', 'charcoal',
                'sketch', 'drawing', 'illustration', 'pigment', 'brushstroke'
            ],
            'textiles': [
                'fabric', 'textile', 'quilt', 'embroidery', 'knitting', 'crochet', 'weaving',
                'tapestry', 'rug', 'carpet', 'blanket', 'pillow', 'cushion', 'needlework',
                'sewing', 'loom', 'yarn', 'thread', 'silk', 'wool', 'cotton', 'linen'
            ],
            'glasswork': [
                'glass', 'stained_glass', 'blown_glass', 'vase', 'bowl', 'sculpture',
                'window', 'lampwork', 'bead', 'mosaic', 'fused_glass', 'goblet', 'decanter',
                'paperweight', 'chandelier', 'mirror', 'prism', 'crystal'
            ],
            'metalwork': [
                'metal', 'sculpture', 'forging', 'welding', 'blacksmith', 'ironwork',
                'copperwork', 'brasswork', 'silversmith', 'goldsmith', 'armor', 'sword',
                'knife', 'tool', 'ornament', 'weathervane', 'gate', 'railing'
            ],
            'candles': [
                'candle', 'wax', 'wick', 'taper', 'pillar', 'votive', 'tea_light',
                'scented', 'beeswax', 'soy_wax', 'paraffin', 'candlestick', 'candleholder',
                'flame', 'melted', 'aromatherapy', 'fragrance', 'essential_oil', 'mold'
            ]
        }

        # Check each prediction against the mappings
        for pred in predictions:
            predicted_class = pred[1].lower()
            print(f"Checking predicted class: {predicted_class}")
            for category, related_classes in category_mappings.items():
                if any(cls in predicted_class for cls in related_classes):
                    print(f"Matched category: {category}")
                    return category

        print("No category match found, returning 'other'")
        return 'other'  # Default category if no match is found

class AuthenticityDocument(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='authenticity_documents')
    document = models.FileField(upload_to='authenticity_documents/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Authenticity Document for {self.product.name}"

class ProductImage(models.Model):
    product = models.ForeignKey(Product, related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(upload_to='product_images/')
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # @receiver(post_save, sender='accounts.ProductImage')
    # def classify_product_image(sender, instance, created, **kwargs):
    #     if created and instance.is_primary:
    #         category_name = instance.product.classify_image(instance.image)
    #         category, _ = Category.objects.get_or_create(name=category_name)
    #         instance.product.category = category
    #         instance.product.save()

    def __str__(self):
        return f"Image for {self.product.name}"

class Review(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review for {self.product.name} by {self.user.username}"

class Order(models.Model):
    STATUS_CHOICES = (
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='processing')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    tracking_number = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return f"Order #{self.id} by {self.user.username}"

    def get_status_display(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    def can_simulate_delivery(self):
        return self.status in ['processing', 'shipped'] and not self.delivered_at

    @property
    def status_progress(self):
        progress_map = {
            'processing': 25,
            'shipped': 75,
            'delivered': 100,
            'cancelled': 0
        }
        return progress_map.get(self.status.lower(), 0)

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantity}x {self.product.name} in Order #{self.order.id}"

class Cart(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey('Product', on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

class Blog(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='blogs')
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    image = models.ImageField(upload_to='blog_images/', blank=True, null=True)
    likes = models.ManyToManyField(User, related_name='liked_blogs', blank=True)

    def __str__(self):
        return self.title

class Comment(models.Model):
    blog = models.ForeignKey(Blog, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comment by {self.user.username} on {self.blog.title}"

class ChatMessage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    thread_name = models.CharField(max_length=50)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user.username}: {self.message}'
    class Meta:
        ordering = ['timestamp']

class DeliveryPartner(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    vehicle_type = models.CharField(max_length=50)
    vehicle_number = models.CharField(max_length=50)
    license_number = models.CharField(max_length=50)
    phone_number = models.CharField(max_length=15)
    profile_picture = models.ImageField(upload_to='delivery_partners/profile_pics/', null=True, blank=True)
    license_image = models.ImageField(upload_to='delivery_partners/licenses/', null=True, blank=True)
    id_proof = models.ImageField(upload_to='delivery_partners/id_proofs/', null=True, blank=True)
    vehicle_registration = models.ImageField(upload_to='delivery_partners/vehicle_registrations/', null=True, blank=True)
    insurance_document = models.ImageField(upload_to='delivery_partners/insurance/', null=True, blank=True)
    status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('suspended', 'Suspended')
    ], default='pending')
    is_available = models.BooleanField(default=True)
    current_location_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    current_location_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.get_full_name()} - {self.vehicle_type}"

    def update_location(self, latitude, longitude):
        self.current_location_lat = latitude
        self.current_location_lng = longitude
        self.save()

    def update_rating(self):
        ratings = self.delivery_ratings.all()
        if ratings:
            avg_rating = sum(r.rating for r in ratings) / len(ratings)
            self.rating = round(avg_rating, 2)
            self.save()

class Delivery(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('picked_up', 'Picked Up'),
        ('in_transit', 'In Transit'),
        ('out_for_delivery', 'Out for Delivery'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled')
    )

    order = models.OneToOneField('Order', on_delete=models.CASCADE, related_name='delivery')
    delivery_partner = models.ForeignKey(DeliveryPartner, on_delete=models.SET_NULL, null=True, related_name='deliveries')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    delivery_address = models.TextField()
    delivery_instructions = models.TextField(blank=True)
    expected_delivery_time = models.DateTimeField()
    actual_delivery_time = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Delivery for Order #{self.order.id}"

    def get_delivery_time(self):
        if self.actual_delivery_time and self.created_at:
            time_diff = self.actual_delivery_time - self.created_at
            return round(time_diff.total_seconds() / 3600, 1)  # Returns hours
        return None

    def mark_as_delivered(self):
        if self.status != 'delivered':
            self.status = 'delivered'
            self.actual_delivery_time = timezone.now()
            self.save()
            
            # Update order status
            self.order.status = 'delivered'
            self.order.delivered_at = timezone.now()
            self.order.save()
            
            # Update delivery partner availability
            if self.delivery_partner:
                self.delivery_partner.is_available = True
                self.delivery_partner.save()

class DeliveryStatusHistory(models.Model):
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name='status_history')
    status = models.CharField(max_length=20, choices=Delivery.STATUS_CHOICES)
    notes = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"Status update for Delivery #{self.delivery.id}: {self.status}"

class DeliveryRating(models.Model):
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name='ratings')
    delivery_partner = models.ForeignKey(DeliveryPartner, on_delete=models.CASCADE, related_name='delivery_ratings')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['delivery', 'user']

    def __str__(self):
        return f"Rating for {self.delivery} by {self.user.username}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.delivery_partner.update_rating()

class DeliveryRoute(models.Model):
    delivery = models.ForeignKey(Delivery, on_delete=models.CASCADE, related_name='route_points')
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"Route point for {self.delivery} at {self.timestamp}"

class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('delivery_assignment', 'Delivery Assignment'),
        ('delivery_update', 'Delivery Update'),
        ('order_status', 'Order Status'),
        ('system', 'System Notification'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES)
    reference_id = models.IntegerField(null=True, blank=True)  # ID of related object (order, delivery, etc.)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.notification_type} - {self.title} for {self.user.username}"
        
    def mark_as_read(self):
        self.is_read = True
        self.save()

class DeliveryEarning(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('paid', 'Paid'),
        ('failed', 'Failed')
    )

    delivery = models.OneToOneField(Delivery, on_delete=models.CASCADE, related_name='earning')
    delivery_partner = models.ForeignKey(DeliveryPartner, on_delete=models.CASCADE, related_name='earnings')
    base_amount = models.DecimalField(max_digits=10, decimal_places=2)  # 20% of order total
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2)  # Base fee + distance fee
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    artisan_share = models.DecimalField(max_digits=10, decimal_places=2)  # 70% of order total
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2)   # 10% of order total
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Earnings for Delivery #{self.delivery.id}"

    def mark_as_processed(self):
        self.status = 'processed'
        self.processed_at = timezone.now()
        self.save()

    def mark_as_paid(self):
        self.status = 'paid'
        self.paid_at = timezone.now()
        self.save()

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['delivery_partner', 'status']),
            models.Index(fields=['created_at']),
        ]
