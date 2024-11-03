from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile
from tensorflow.keras.applications.efficientnet import EfficientNetB0, preprocess_input, decode_predictions
from tensorflow.keras.preprocessing import image
import numpy as np
# import tensorflow as tf
from django.db.models.signals import post_save
from django.dispatch import receiver
import io

class User(AbstractUser):
    USER_TYPE_CHOICES = (
        ('artisan', 'Artisan'),
        ('customer', 'Customer'),
        ('admin', 'Admin'),
    )
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES, default="customer")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status = models.CharField(max_length=20, default='active')

    def __str__(self):
        return self.username

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

    def classify_image(self, image_file):
        print("Loading custom EfficientNet model...")
        model = tf.keras.models.load_model('custom_efficientnet_model.h5')
        print("Model loaded successfully")

        print(f"Image file type: {type(image_file)}")
        
        if isinstance(image_file, (InMemoryUploadedFile, TemporaryUploadedFile)):
            print("Processing UploadedFile")
            img = image.load_img(io.BytesIO(image_file.read()), target_size=(224, 224))
        else:
            print("Processing file path")
            img = image.load_img(image_file, target_size=(224, 224))
        
        print("Image loaded successfully")
        x = image.img_to_array(img)
        x = np.expand_dims(x, axis=0)
        x = x / 255.0  # Normalize the image

        print("Making prediction...")
        preds = model.predict(x)
        print("Prediction made successfully")
        predicted_class_index = np.argmax(preds[0])
        category_names = list(self.CATEGORY_CHOICES)
        predicted_category = category_names[predicted_class_index]
        print(f"Predicted category: {predicted_category}")

        return predicted_category

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

    @receiver(post_save, sender='accounts.ProductImage')
    def classify_product_image(sender, instance, created, **kwargs):
        if created and instance.is_primary:
            category_name = instance.product.classify_image(instance.image)
            category, _ = Category.objects.get_or_create(name=category_name)
            instance.product.category = category
            instance.product.save()

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
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='processing')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    tracking_number = models.CharField(max_length=100, null=True, blank=True)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def update_status(self, new_status):
        self.status = new_status
        if new_status == 'shipped' and not self.shipped_at:
            self.shipped_at = timezone.now()
        elif new_status == 'delivered' and not self.delivered_at:
            self.delivered_at = timezone.now()
        self.save()
    def simulate_delivery(self):
        if self.status == 'processing':
            self.update_status('shipped')
        elif self.status == 'shipped':
            self.update_status('delivered')
        self.save()

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.product.name} in Order {self.order.id}"

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