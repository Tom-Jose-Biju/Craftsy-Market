from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile
from django.utils import timezone
from django.db import transaction, models
from django.conf import settings
from decimal import Decimal
from PIL import Image
import torch
import logging
import json
import io
import csv
from django.urls import reverse
from datetime import datetime

from .models import (
    User, Product, Order, Delivery, DeliveryPartner,
    DeliveryStatusHistory, DeliveryRoute, Notification,
    DeliveryEarning, Cart, CartItem, Wishlist
)
from .utils import is_delivery_partner, get_image_classifier, process_delivery_earnings

logger = logging.getLogger(__name__)

import json
import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse, HttpResponse, FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.utils import timezone
from datetime import timedelta
from django.dispatch import receiver
from django.db.models.signals import post_save
from django.db.models import Q, Sum, Avg, Count, F, FloatField, ExpressionWrapper, Case, When, DurationField, DecimalField, Value, Max, IntegerField
from django.core.serializers.json import DjangoJSONEncoder
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.db.models.functions import TruncMonth, Cast, TruncDate, TruncWeek, Extract, ExtractHour
from django.core.files.uploadedfile import InMemoryUploadedFile
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from io import BytesIO
import matplotlib.pyplot as plt
from django.core.files.storage import default_storage, FileSystemStorage
import tempfile
from django.core.files.base import ContentFile
from PIL import Image
import io
import torch
from transformers import ViTImageProcessor, ViTForImageClassification
from django.core.mail import send_mail
from functools import lru_cache
from django.core.cache import cache
from django.db import transaction
from datetime import datetime, timedelta
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.shortcuts import get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Delivery, DeliveryRoute, DeliveryStatusHistory
from .utils import is_delivery_partner

from .forms import (
    ArtisanProfileForm, ProductForm, ProfileForm, UserRegistrationForm,
    ReviewForm, BlogForm
)
from .models import (
    Artisan, Product, ProductImage, Profile, User,
    Order, OrderItem, Cart, CartItem, Category,
    Review, Blog, AuthenticityDocument, Comment,
    Delivery, DeliveryStatusHistory, DeliveryPartner, DeliveryRating,
    Notification, DeliveryEarning
)

stripe.api_key = settings.STRIPE_SECRET_KEY

# Helper Functions
def is_delivery_partner(user):
    """Check if user is a delivery partner"""
    return hasattr(user, 'delivery_partner') and user.delivery_partner is not None

def get_active_delivery(delivery_partner):
    """Get the active deliveries for a delivery partner"""
    return Delivery.objects.filter(
        delivery_partner=delivery_partner,
        status__in=['pending', 'picked_up', 'in_transit', 'out_for_delivery']
    ).order_by('expected_delivery_time')  # Order by expected delivery time to prioritize urgent deliveries

@lru_cache(maxsize=1)
def get_image_classifier():
    """
    Load and cache the image classification model.
    Uses LRU cache to avoid loading the model multiple times.
    """
    # Try to get the model from the Django cache first
    cached_model = cache.get('vit_image_model')
    cached_processor = cache.get('vit_image_processor')
    
    if cached_model is not None and cached_processor is not None:
        print("Using cached model from Django cache")
        return cached_processor, cached_model
    
    print("Loading model from transformers library")
    # If not in cache, load the model
    processor = ViTImageProcessor.from_pretrained('google/vit-base-patch16-224')
    model = ViTForImageClassification.from_pretrained('google/vit-base-patch16-224')
    
    # Store in Django cache for 1 hour (3600 seconds)
    cache.set('vit_image_processor', processor, 3600)
    cache.set('vit_image_model', model, 3600)
    
    return processor, model

@login_required
def classify_image(request):
    """
    View function for classifying uploaded images using the pre-trained model.
    Uses the get_image_classifier helper function to load the model.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST requests are supported'}, status=405)
    
    if 'image' not in request.FILES:
        return JsonResponse({'error': 'No image file provided'}, status=400)
    
    try:
        start_time = timezone.now()
        image_file = request.FILES['image']
        
        # Open and resize image for faster processing
        image = Image.open(image_file).convert('RGB')
        max_size = (224, 224)  # Standard size for ViT models
        image.thumbnail(max_size, Image.LANCZOS)
        
        # Get the classifier model
        processor, model = get_image_classifier()
        
        # Process the image
        inputs = processor(images=image, return_tensors="pt")
        outputs = model(**inputs)
        logits = outputs.logits
        
        # Get top-5 predictions for better context
        probs = torch.nn.functional.softmax(logits, dim=-1)[0]
        top5_probs, top5_indices = torch.topk(probs, 5)
        
        # Convert top predictions to list
        top_predictions = []
        for i, (prob, idx) in enumerate(zip(top5_probs.tolist(), top5_indices.tolist())):
            top_predictions.append({
                'class': model.config.id2label[idx],
                'confidence': round(prob * 100, 2)
            })
        
        # Get top prediction
        predicted_class_idx = logits.argmax(-1).item()
        predicted_class = model.config.id2label[predicted_class_idx]
        confidence = probs[predicted_class_idx].item()
        
        # Map ViT class to one of the product categories (you can expand this mapping)
        # First, let's get actual categories from the database
        actual_categories = list(Category.objects.filter(is_active=True).values_list('name', flat=True))
        logger.info(f"Available categories in database: {actual_categories}")
        logger.info(f"Predicted class: {predicted_class}")
        
        # Default mapping (fallback)
        category_mapping = {
            # Map to exact category names in your database
            'pitcher': 'Pottery',
            'vase': 'Pottery',
            'ceramic': 'Pottery',
            'pottery': 'Pottery',
            'bowl': 'Pottery',
            'cup': 'Pottery',
            'mug': 'Pottery',
            'plate': 'Pottery',
            'pot': 'Pottery',
            
            'necklace': 'Jewelry',
            'bracelet': 'Jewelry',
            'ring': 'Jewelry',
            'earring': 'Jewelry',
            'pendant': 'Jewelry',
            'metal': 'Jewelry',
            'gold': 'Jewelry',
            'silver': 'Jewelry',
            'gemstone': 'Jewelry',
            'bead': 'Jewelry',
            
            'woodwork': 'Woodworking',
            'carving': 'Woodworking',
            'wooden': 'Woodworking',
            'wood': 'Woodworking',
            'furniture': 'Woodworking',
            'table': 'Woodworking',
            'chair': 'Woodworking',
            
            'painting': 'Painting',
            'canvas': 'Painting',
            'artwork': 'Painting',
            'portrait': 'Painting',
            'landscape': 'Painting',
            'art': 'Painting',
        }
        
        # Find appropriate category
        classification = None
        
        # First try direct matches with predicted class
        for pred_word in predicted_class.lower().split():
            for category_name in actual_categories:
                if pred_word in category_name.lower() or category_name.lower() in pred_word:
                    classification = category_name
                    logger.info(f"Direct match found: {classification}")
                    break
        
        # If no direct match, try mapping
        if not classification:
            for key_term, category_value in category_mapping.items():
                if key_term.lower() in predicted_class.lower():
                    # Find the best matching actual category
                    for actual_cat in actual_categories:
                        if category_value.lower() in actual_cat.lower() or actual_cat.lower() in category_value.lower():
                            classification = actual_cat
                            logger.info(f"Mapped match found: {classification} via {key_term} -> {category_value}")
                            break
                    if classification:
                        break
        
        # For top predictions, also look at other high confidence classes if we still don't have a match
        if not classification:
            for pred in top_predictions[:3]:
                pred_class = pred['class'].lower()
                
                # Try direct matches with pred_class
                for pred_word in pred_class.split():
                    for category_name in actual_categories:
                        if pred_word in category_name.lower() or category_name.lower() in pred_word:
                            classification = category_name
                            logger.info(f"Top prediction direct match found: {classification}")
                            break
                    if classification:
                        break
                
                # If still no match, try with mapping
                if not classification:
                    for key_term, category_value in category_mapping.items():
                        if key_term.lower() in pred_class:
                            # Find the best matching actual category
                            for actual_cat in actual_categories:
                                if category_value.lower() in actual_cat.lower() or actual_cat.lower() in category_value.lower():
                                    classification = actual_cat
                                    logger.info(f"Top prediction mapped match found: {classification} via {key_term} -> {category_value}")
                                    break
                            if classification:
                                break
                
                if classification:
                    break
        
        # Fallback if we still couldn't find a match
        if not classification and actual_categories:
            classification = 'Other' if 'Other' in actual_categories else actual_categories[0]
            logger.info(f"No match found, using fallback: {classification}")
        
        end_time = timezone.now()
        processing_time = (end_time - start_time).total_seconds()
        
        return JsonResponse({
            'success': True,
            'classification': classification or 'Other',
            'confidence': round(confidence * 100, 2),
            'top_predictions': top_predictions,
            'processing_time_seconds': processing_time
        })
    except Exception as e:
        logger.error(f"Error in image classification: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

# Home and Authentication Views
def home(request):
    return render(request, 'home.html')

def register(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.save()
            messages.success(request, 'Registration successful. Please log in.')
            return redirect('login')
        else:
            for field in form:
                for error in field.errors:
                    messages.error(request, f"{field.label}: {error}")
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UserRegistrationForm()
    return render(request, 'register.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        # Allow superuser with username 'admin' and password 'admin' to bypass validation
        if username == 'admin' and password == 'admin':
            user = get_object_or_404(User, username=username)
            backend = 'django.contrib.auth.backends.ModelBackend'  # Specify the backend
        else:
            # Authenticate using the default backend
            user = authenticate(request, username=username, password=password)
            backend = 'django.contrib.auth.backends.ModelBackend'  # Use the ModelBackend

        # Debugging output
        print(f"Username: {username}, Password: {password}, User: {user}, Backend: {backend}")  # Check the authentication result
        
        if user is not None:
            user.backend = backend  # Set the backend on the user
            login(request, user, backend=backend)  # Provide the backend here
            request.session['user_id'] = user.id
            request.session['username'] = user.username
            
            # Redirect based on user type
            if user.is_staff:
                return redirect('admin_dashboard')
            elif user.user_type == 'artisan':
                return redirect('artisan_home')  # Redirect to artisan home
            elif user.user_type == 'delivery_partner':
                return redirect('delivery_dashboard')  # Redirect to delivery dashboard
            else:
                return redirect('home')
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'login.html', {
        'next': request.GET.get('next', '')
    })

def signout(request):
    if request.method in ['GET', 'POST']:
        logout(request)
        request.session.flush()
        return redirect('home')
    return JsonResponse({'error': 'Method not allowed'}, status=405)

# Admin Views
@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_dashboard(request):
    # Get notification data
    new_orders_count = Order.objects.filter(status='pending').count()
    new_artisans_count = User.objects.filter(user_type='artisan', is_active=False).count()
    pending_delivery_partners_count = DeliveryPartner.objects.filter(status='pending').count()
    
    # Get recent orders
    recent_orders = Order.objects.order_by('-created_at')[:5]
    
    # Get top selling products
    top_products = Product.objects.annotate(
        total_ordered=Sum('orderitem__quantity')
    ).order_by('-total_ordered')[:5]
    
    # Get total revenue
    total_revenue = Order.objects.filter(status='delivered').aggregate(
        total=Sum('total_price')
    )['total'] or 0
    
    # Get unassigned orders
    unassigned_orders = Order.objects.filter(
        status='processing'
    ).exclude(
        id__in=Delivery.objects.values_list('order_id', flat=True)
    ).count()

    context = {
        'new_orders_count': new_orders_count,
        'new_artisans_count': new_artisans_count,
        'pending_delivery_partners_count': pending_delivery_partners_count,
        'recent_orders': recent_orders,
        'top_products': top_products,
        'total_revenue': total_revenue,
        'unassigned_orders': unassigned_orders,
    }
    
    return render(request, 'admin_dashboard.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_users(request):
    if not request.user.is_staff:
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    users = User.objects.all().order_by('-date_joined')
    context = {
        'users': users,
    }
    return render(request, 'admin_users.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_artisans(request):
    if request.method == 'POST':
        document_id = request.POST.get('document_id')
        action = request.POST.get('action')
        
        if document_id and action in ['verify', 'reject']:
            try:
                document = get_object_or_404(AuthenticityDocument, id=document_id)
                if action == 'verify':
                    document.is_verified = True
                    message = 'Document verified successfully.'
                else:
                    document.is_verified = False
                    message = 'Document rejected successfully.'
                document.save()
                return JsonResponse({'success': True, 'message': message})
            except Exception as e:
                return JsonResponse({'success': False, 'message': str(e)}, status=500)
        else:
            return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)
    
    artisans = User.objects.filter(user_type='artisan')
    authenticity_documents = AuthenticityDocument.objects.select_related('product__artisan__user').all()
    
    context = {
        'artisans': artisans,
        'authenticity_documents': authenticity_documents,
    }
    return render(request, 'admin_artisans.html', context)

@login_required
@login_required
def admin_products(request):
    if not request.user.is_staff:
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    products = Product.objects.all().select_related('category', 'artisan__user')
    total_products = products.count()
    total_value = products.aggregate(Sum('price'))['price__sum'] or 0
    average_price = products.aggregate(Avg('price'))['price__avg'] or 0

    categories = Category.objects.annotate(product_count=Count('products'))
    category_names = list(categories.values_list('name', flat=True))
    category_counts = list(categories.values_list('product_count', flat=True))

    context = {
        'products': products,
        'total_products': total_products,
        'total_value': round(total_value, 2),
        'average_price': round(average_price, 2),
        'category_names': json.dumps(category_names),
        'category_counts': json.dumps(category_counts),
    }
    return render(request, 'admin_products.html', context)

@login_required
def view_product(request, product_id):
    if not request.user.is_staff:
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    product = get_object_or_404(Product, id=product_id)
    return JsonResponse({
        'id': product.id,
        'name': product.name,
        'description': product.description,
        'price': str(product.price),
        'stock': product.stock,
        'category': product.category.name,
        'artisan': product.artisan.user.username,
        'created_at': product.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        'is_in_stock': product.is_in_stock(),
    })

@login_required
def edit_product(request, product_id):
    if not request.user.is_staff:
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    product = get_object_or_404(Product, id=product_id)
    if request.method == 'POST':
        # Update product logic here
        # Remember to handle the form data and save the product
        messages.success(request, f"Product '{product.name}' has been updated successfully.")
        return redirect('admin_products')
    
    # If it's a GET request, you might want to return a form or product data
    return JsonResponse({
        'id': product.id,
        'name': product.name,
        'description': product.description,
        'price': str(product.price),
        'stock': product.stock,
        'category_id': product.category.id,
    })

@login_required
def delete_product(request, product_id):
    if request.user.user_type != 'artisan':
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    artisan = get_object_or_404(Artisan, user=request.user)
    product = get_object_or_404(Product, id=product_id, artisan=artisan)
    
    if request.method == 'POST':
        product.delete()
        messages.success(request, "Product deleted successfully!")
        return redirect('artisan_products')
    
    # If it's not a POST request, redirect to artisan_products
    return redirect('artisan_products')

@login_required
@login_required
def admin_add_category(request):
    if not request.user.is_staff:
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    if request.method == 'POST':
        category_name = request.POST.get('category_name')
        parent_id = request.POST.get('parent_category')
        is_subcategory = request.POST.get('is_subcategory') == 'on'
        
        if category_name:
            parent = None
            if parent_id:
                parent = Category.objects.get(id=parent_id)
            
            if is_subcategory and not parent:
                messages.error(request, "Please select a parent category for the subcategory.")
            else:
                # Check if a category with this name already exists
                if Category.objects.filter(name=category_name).exists():
                    messages.error(request, f"A category with the name '{category_name}' already exists.")
                else:
                    Category.objects.create(name=category_name, parent=parent)
                    messages.success(request, f"{'Subcategory' if is_subcategory else 'Category'} '{category_name}' has been added successfully.")
                return redirect('admin_add_category')
        else:
            messages.error(request, "Category name cannot be empty.")
    
    categories = Category.objects.all()
    return render(request, 'admin_add_category.html', {'categories': categories})

@login_required
def admin_edit_category(request, category_id):
    if not request.user.is_staff:
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    category = get_object_or_404(Category, id=category_id)
    
    if request.method == 'POST':
        category_name = request.POST.get('category_name')
        parent_id = request.POST.get('parent_category')
        if category_name:
            category.name = category_name
            if parent_id:
                parent = Category.objects.get(id=parent_id)
                if parent != category:
                    category.parent = parent
                else:
                    category.parent = None
            else:
                category.parent = None
            
            category.save()
            messages.success(request, f"Category '{category.name}' has been updated successfully.")
            return redirect('admin_add_category')
        else:
            messages.error(request, "Category name cannot be empty.")
    
    categories = Category.objects.exclude(id=category_id)
    return render(request, 'admin_add_category.html', {'category': category, 'categories': categories})


@login_required
@require_POST
def admin_delete_category(request, category_id):
    if not request.user.is_staff:
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    category = get_object_or_404(Category, id=category_id)
    category.delete()
    messages.success(request, f"Category '{category.name}' has been deleted successfully.")
    return redirect('admin_add_category')

@login_required
@require_POST
def disable_category(request, category_id):
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'error': "You don't have access to this action."}, status=403)
    
    category = get_object_or_404(Category, id=category_id)
    category.is_active = False
    category.save()
    
    return JsonResponse({'success': True})

@login_required
@require_POST
def enable_category(request, category_id):
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'error': "You don't have access to this action."}, status=403)
    
    category = get_object_or_404(Category, id=category_id)
    category.is_active = True
    category.save()
    
    return JsonResponse({'success': True})

# Artisan Views
def artisan_register(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.user_type = 'artisan'
            user.save()
            Artisan.objects.create(user=user)
            messages.success(request, 'Registration successful. Please log in.')
            return redirect('login')
    else:
        form = UserRegistrationForm()
    return render(request, 'artisan_register.html', {'form': form})

@login_required
def artisan_home(request):
    if request.user.user_type != 'artisan':
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    return render(request, 'artisan.html')

@login_required
def artisan_profile(request):
    artisan = get_object_or_404(Artisan, user=request.user)
    
    if request.method == 'POST':
        if 'profile_picture' in request.FILES:
            artisan.profile_picture = request.FILES['profile_picture']
            artisan.save()
            messages.success(request, 'Profile picture updated successfully.')
            return redirect('artisan_profile')
        elif request.POST:  # Changed else to elif
            form = ArtisanProfileForm(request.POST, instance=artisan)
            if form.is_valid():
                form.save()
                messages.success(request, 'Profile updated successfully.')
                return redirect('artisan_profile')
            else:
                messages.error(request, 'Error updating profile. Please check the form.')
    else:
        form = ArtisanProfileForm(instance=artisan)
    
    context = {
        'artisan': artisan,
        'form': form,
        'total_products': Product.objects.filter(artisan=artisan).count(),
        'total_orders': Order.objects.filter(items__product__artisan=artisan).distinct().count(),
        'average_rating': Review.objects.filter(product__artisan=artisan).aggregate(Avg('rating'))['rating__avg'] or 0,
    }
    return render(request, 'artisan_profile.html', context)

def artisanview(request):
    return render(request, 'artisan.html')



# Product Views
@login_required
@login_required
def add_product(request):
    if request.user.user_type != 'artisan':
        return JsonResponse({'success': False, 'message': "Only artisans can add products."})
    
    categories = Category.objects.filter(is_active=True)

    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                product = form.save(commit=False)
                artisan = get_object_or_404(Artisan, user=request.user)
                product.artisan = artisan
                product.save()

                images = request.FILES.getlist('images')
                if not images:
                    raise ValueError("At least one image is required.")

                for i, image in enumerate(images):
                    ProductImage.objects.create(
                        product=product,
                        image=image,
                        is_primary=(i == 0)
                    )

                # Return only necessary information
                return JsonResponse({
                    'success': True, 
                    'message': "Product added successfully!",
                    'product_id': product.id
                })
            except Exception as e:
                return JsonResponse({'success': False, 'message': str(e)})
        else:
            errors = {field: error[0] for field, error in form.errors.items()}
            return JsonResponse({'success': False, 'errors': errors})
    else:
        form = ProductForm()

    return render(request, 'add_product.html', {'form': form, 'categories': categories})

from django.db.models import Q

def products(request):
    products = Product.objects.filter(is_active=True)
    categories = Category.objects.filter(parent=None).prefetch_related('subcategories')# Only active categories
    search_query = request.GET.get('search')
    category_id = request.GET.get('category')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')

    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(artisan__user__username__icontains=search_query)
        )

    if category_id:
        products = products.filter(category_id=category_id)

    if min_price:
        try:
            min_price = float(min_price)
            if min_price >= 0:
                products = products.filter(price__gte=min_price)
        except ValueError:
            pass

    if max_price:
        try:
            max_price = float(max_price)
            if max_price >= 0:
                products = products.filter(price__lte=max_price)
        except ValueError:
            pass

    for product in products:
        product.reviews_json = json.dumps(list(product.reviews.values('rating')), cls=DjangoJSONEncoder)

    context = {
        'products': products,
        'categories': categories,
        'search_query': search_query,
    }
    
    return render(request, 'products.html', context)

@login_required
def get_artisan_info(request, artisan_id):
    artisan = get_object_or_404(Artisan, id=artisan_id)
    product_count = Product.objects.filter(artisan=artisan, is_active=True).count()
    average_rating = Review.objects.filter(product__artisan=artisan).aggregate(Avg('rating'))['rating__avg'] or 0

    data = {
        'name': artisan.user.username,
        'image_url': artisan.profile_picture.url if artisan.profile_picture else '/path/to/default/image.jpg',
        'bio': artisan.bio or 'No bio available',
        'product_count': product_count,
        'average_rating': average_rating,
    }
    return JsonResponse(data)
    
def artisan_products_view(request, artisan_id):
    artisan = get_object_or_404(Artisan, id=artisan_id)
    products = Product.objects.filter(artisan=artisan, is_active=True)
    context = {
        'artisan': artisan,
        'products': products,
    }
    return render(request, 'artisan_products.html', context)
    
@login_required
@login_required
@login_required
def artisan_products(request):
    if request.user.user_type != 'artisan':
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    artisan = get_object_or_404(Artisan, user=request.user)
    products = Product.objects.filter(artisan=artisan)
    
    # Get categories with product count
    categories = Category.objects.annotate(
        product_count=Count('products', filter=Q(products__artisan=artisan))
    ).filter(product_count__gt=0)
    
    # Filter products by category if a category is selected
    selected_category = request.GET.get('category')
    if selected_category:
        products = products.filter(category__id=selected_category)
    
    # Get top selling products (only active ones)
    top_selling_products = Product.objects.filter(artisan=artisan, is_active=True).annotate(
        sales_count=Count('orderitem')
    ).order_by('-sales_count')[:3]
    
    context = {
        'products': products,
        'categories': categories,
        'selected_category': selected_category,
        'top_selling_products': top_selling_products,
    }
    return render(request, 'artisan_products.html', context)

@login_required
def update_product(request, product_id):
    if request.user.user_type != 'artisan':
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    artisan = get_object_or_404(Artisan, user=request.user)  # Get the Artisan instance
    product = get_object_or_404(Product, id=product_id, artisan=artisan)  # Use the Artisan instance
    
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        if form.is_valid():
            form.save()

            new_images = request.FILES.getlist('images')
            for image in new_images:
                ProductImage.objects.create(product=product, image=image)

            messages.success(request, "Product updated successfully!")
            return redirect('artisan_products')
    else:
        form = ProductForm(instance=product)
    
    return render(request, 'update_product.html', {'form': form, 'product': product})

@login_required
@require_POST
def toggle_product_status(request, product_id):
    if request.user.user_type != 'artisan':
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    artisan = get_object_or_404(Artisan, user=request.user)
    product = get_object_or_404(Product, id=product_id, artisan=artisan)
    
    product.is_active = not product.is_active
    product.save()
    
    status = "enabled" if product.is_active else "disabled"
    messages.success(request, f"Product '{product.name}' has been {status}.")
    return redirect('artisan_products')

@login_required
@require_POST
def disable_product(request, product_id):
    if request.user.user_type != 'artisan':
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    artisan = get_object_or_404(Artisan, user=request.user)
    product = get_object_or_404(Product, id=product_id, artisan=artisan)
    
    product.is_active = False
    product.save()
    
    messages.success(request, f"Product '{product.name}' has been disabled.")
    return redirect('artisan_products')

from django.db.models import Avg
from .models import Review, Product
from .forms import ReviewForm
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from decimal import Decimal

def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    reviews = product.reviews.all().order_by('-created_at')
    average_rating = reviews.aggregate(Avg('rating'))['rating__avg']

    related_products = Product.objects.filter(category=product.category).exclude(id=product.id)[:3]
    has_authenticity_certificate = AuthenticityDocument.objects.filter(product=product).exists()

    gst_rate = Decimal(str(settings.GST_RATE))
    gst_amount = product.price * gst_rate
    total_price = product.price + gst_amount
    
    context = {
        'product': product,
        'reviews': reviews,
        'average_rating': average_rating,
        'in_stock': product.is_in_stock(),
        'inventory_count': product.inventory,
        'related_products': related_products,
        'has_authenticity_certificate': has_authenticity_certificate,
        'gst_amount': gst_amount,
        'total_price': total_price,
        'GST_RATE': gst_rate * 100,
    }
    return render(request, 'product_detail.html', context)

@login_required
def artisan_order_details(request):
    artisan = get_object_or_404(Artisan, user=request.user)
    orders = Order.objects.filter(items__product__artisan=artisan).distinct()

    # Calculate total price for each order
    for order in orders:
        order.total_price = sum(item.price * item.quantity for item in order.items.all())
        order.save()

    total_orders = orders.count()
    pending_orders = orders.filter(status='processing').count()
    completed_orders = orders.filter(status='delivered').count()
    total_revenue = sum(order.total_price for order in orders.filter(status='delivered'))

    paginator = Paginator(orders, 10)  # Show 10 orders per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'orders': page_obj,
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'completed_orders': completed_orders,
        'total_revenue': total_revenue,
    }
    return render(request, 'artisan_order_details.html', context)

# Profile Views
@login_required
def profile(request):
    profile = Profile.objects.get(user=request.user)
    if request.method == 'POST':
        if 'profile_image' in request.FILES:
            profile.profile_image = request.FILES['profile_image']
            profile.save()
            messages.success(request, 'Profile picture updated successfully.')
            return redirect('profile')
        else:
            # Handle address and other profile information
            profile.street_address = request.POST.get('street_address', '')
            profile.city = request.POST.get('city', '')
            profile.state = request.POST.get('state', '')
            profile.postal_code = request.POST.get('postal_code', '')
            profile.country = request.POST.get('country', '')
            profile.phone_number = request.POST.get('phone_number', '')
            profile.save()
            
            messages.success(request, 'Profile information updated successfully.')
            return redirect('profile')

    return render(request, 'profile.html', {'profile': profile})

@login_required
@require_POST
def deactivate_account(request):
    user = request.user
    if user.is_superuser and User.objects.filter(is_superuser=True, is_active=True).count() == 1:
        return JsonResponse({'success': False, 'message': 'Cannot deactivate the last active admin account.'})
    user.is_active = False
    user.save()
    logout(request)
    return JsonResponse({'success': True})

# Checkout and Payment Views
@require_http_methods(["GET", "POST"])
@login_required
def checkout(request):
    """Unified checkout view."""
    try:
        # Get user's cart and related items
        cart = Cart.objects.get(user=request.user)
        cart_items = CartItem.objects.filter(cart=cart).select_related('product')
        
        if not cart_items.exists():
            messages.warning(request, 'Your cart is empty.')
            return redirect('cart')
        
        # Calculate total amount
        total_amount = Decimal('0.00')
        for item in cart_items:
            total_amount += item.product.price * item.quantity
        
        if request.method == 'POST':
            try:
                # Process checkout form
                address = request.POST.get('address')
                city = request.POST.get('city')
                state = request.POST.get('state')
                zipcode = request.POST.get('zipcode')
                
                if not all([address, city, state, zipcode]):
                    messages.error(request, 'Please fill in all address fields.')
                    return redirect('checkout')
                
                try:
                    with transaction.atomic():
                        # Create order
                        order = Order.objects.create(
                            user=request.user,
                            total_amount=total_amount,
                            shipping_address=f"{address}, {city}, {state} {zipcode}",
                            status='pending'
                        )
                        
                        # Create order items from cart
                        order_items = []
                        for cart_item in cart_items:
                            order_items.append(OrderItem(
                                order=order,
                                product=cart_item.product,
                                quantity=cart_item.quantity,
                                price=cart_item.product.price
                            ))
                        
                        # Bulk create order items
                        OrderItem.objects.bulk_create(order_items)
                        
                        # Clear the cart after successful order creation
                        cart_items.delete()
                        
                        # Redirect to payment
                        return redirect('create_checkout_session')
                        
                except Exception as e:
                    messages.error(request, f'An error occurred during checkout: {str(e)}')
                    return redirect('checkout')
            except Exception as e:
                messages.error(request, f'An error processing form data: {str(e)}')
                return redirect('checkout')
        
        # Handle GET request
        context = {
            'cart_items': cart_items,
            'total_amount': total_amount,
            'page_title': 'Checkout'
        }
        return render(request, 'checkout.html', context)
    except Cart.DoesNotExist:
        messages.error(request, 'Cart not found.')
        return redirect('cart')
    except Exception as e:
        messages.error(request, f'An error occurred: {str(e)}')
        return redirect('cart')

@login_required
def create_checkout_session(request):
    """Create a checkout session for payment processing."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    try:
        # Get cart items
        cart_items = CartItem.objects.filter(user=request.user)
        if not cart_items.exists():
            return JsonResponse({'error': 'Cart is empty'}, status=400)

        # Calculate total price
        total_price = sum(item.quantity * item.product.price for item in cart_items)

        # Create order
        order = Order.objects.create(
            user=request.user,
            total_price=total_price,
            status='pending'
        )

        # Create order items
        for item in cart_items:
            OrderItem.objects.create(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.price
            )

        # Redirect to payment success page
        return JsonResponse({
            'success': True,
            'redirect_url': reverse('payment_success')
        })

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

@require_GET
def payment_success(request):
    try:
        cart, created = Cart.objects.get_or_create(user=request.user)
        cart_items = cart.items.all()
        
        if not cart_items:
            messages.warning(request, "Your cart is empty.")
            return redirect('home')

        total_price = sum(item.product.price * item.quantity for item in cart_items)

        # Create the order with auto-now fields
        order = Order.objects.create(
            user=request.user,
            total_price=total_price,
            status='processing'  # Changed from 'confirmed' to 'processing'
        )

        # Create order items and update inventory
        for cart_item in cart_items:
            if cart_item.product.inventory >= cart_item.quantity:
                OrderItem.objects.create(
                    order=order,
                    product=cart_item.product,
                    quantity=cart_item.quantity,
                    price=cart_item.product.price
                )
                # Update inventory
                cart_item.product.inventory -= cart_item.quantity
                cart_item.product.save()
            else:
                messages.warning(request, f"{cart_item.product.name} is out of stock. It has been removed from your order.")

        # Clear the cart after successful payment
        cart_items.delete()
        
        # Create notification for the customer
        Notification.objects.create(
            user=request.user,
            title='Order Placed Successfully',
            message=f'Your order #{order.id} has been placed successfully.',
            notification_type='order_update'
        )
        
        # Create notification for admin
        admin_users = User.objects.filter(is_staff=True)
        for admin in admin_users:
            Notification.objects.create(
                user=admin,
                title='New Order Received',
                message=f'New order #{order.id} requires delivery assignment.',
                notification_type='order_update'
            )
        
        messages.success(request, 'Order placed successfully! You will be notified once your order is assigned to a delivery partner.')
        return redirect('order_detail', order_id=order.id)
        
    except Exception as e:
        messages.error(request, f"An error occurred while processing your order: {str(e)}")
        return redirect('cart')

@login_required
def payment_cancel(request):
    messages.warning(request, "Payment cancelled. Your cart items are still saved.")
    return redirect('cart')


@login_required
def order_history(request):
    # Get all orders for the current user with prefetched data
    orders = Order.objects.filter(user=request.user)\
        .prefetch_related(
            'items__product',
            'delivery__delivery_partner__user',
            'delivery__status_history',
            'delivery__ratings'
        )
    
    # Manual approach - get all orders and filter them in Python
    all_orders = list(orders)
    
    # Create separate lists for active and delivered orders
    delivered_orders = []
    active_orders = []
    
    # Create a dict to store delivery ratings for each order
    delivery_ratings = {}
    
    for order in all_orders:
        # Check for delivery partner ratings
        if hasattr(order, 'delivery') and order.delivery:
            # Get ratings for this delivery
            ratings = list(order.delivery.ratings.all())
            delivery_ratings[order.id] = ratings
        
        # Categorize by delivery status
        if (hasattr(order, 'delivery') and order.delivery and 
            order.delivery.status.lower() in ['delivered', 'complete', 'completed']):
            delivered_orders.append(order)
        elif order.status.lower() == 'delivered':
            delivered_orders.append(order)
        else:
            active_orders.append(order)
    
    # Function to get sort key for ordering
    def sort_key(order):
        # Check if order has delivery
        has_delivery = bool(hasattr(order, 'delivery') and order.delivery)
        assignment_date = getattr(getattr(order, 'delivery', None), 'created_at', None)
        return (0 if not has_delivery else 1, assignment_date or timezone.now(), order.created_at)
    
    # Sort active orders (assigned first, then by date - reversed for newest first)
    active_orders.sort(key=sort_key, reverse=True)
    
    # Debug output
    logger.info(f"Active orders count: {len(active_orders)}")
    logger.info(f"Active orders: {[(o.id, o.status, getattr(getattr(o, 'delivery', None), 'status', 'No delivery')) for o in active_orders if hasattr(o, 'delivery')]}")
    logger.info(f"Delivered orders count: {len(delivered_orders)}")
    logger.info(f"Delivered orders: {[(o.id, o.status, getattr(getattr(o, 'delivery', None), 'status', 'No delivery')) for o in delivered_orders if hasattr(o, 'delivery')]}")
    
    context = {
        'active_orders': active_orders,
        'delivered_orders': delivered_orders,
        'delivery_ratings': delivery_ratings,
        'debug_active_orders': [(o.id, o.status, getattr(getattr(o, 'delivery', None), 'status', 'No delivery')) for o in active_orders],
        'debug_delivered_orders': [(o.id, o.status, getattr(getattr(o, 'delivery', None), 'status', 'No delivery')) for o in delivered_orders]
    }
    
    return render(request, 'order_history.html', context)

@login_required
@login_required
def order_detail(request, order_id):
    try:
        order = Order.objects.get(id=order_id)
        
        # Check permissions
        if not (request.user == order.user or request.user.is_staff or 
                (hasattr(order, 'delivery') and order.delivery and order.delivery.delivery_partner.user == request.user)):
            messages.error(request, "You don't have permission to view this order.")
            return redirect('order_history')
        
        # Get order items with related data
        order_items = order.items.all().prefetch_related(
            'product',
            'product__reviews',
            'product__artisan'
        )
        
        # Get user profile
        profile = order.user.profile
        
        # Get delivery information
        delivery = None
        delivery_status_history = None
        delivery_rating = None
        try:
            delivery = order.delivery
            if delivery:
                delivery_status_history = delivery.status_history.all().order_by('-timestamp')
                delivery_rating = delivery.ratings.filter(user=request.user).first()
        except Exception as e:
            logger.error(f"Error fetching delivery data for order {order_id}: {str(e)}")
        
        # Calculate status progress
        status_map = {
            'processing': 25,
            'shipped': 75,
            'delivered': 100,
            'cancelled': 0
        }
        status_progress = status_map.get(order.status.lower(), 0)
    
        context = {
            'order': order,
            'order_items': order_items,
            'profile': profile,
            'delivery': delivery,
            'delivery_status_history': delivery_status_history,
            'delivery_rating': delivery_rating,
            'status_progress': status_progress
        }
            
        return render(request, 'order_detail.html', context)
    except Order.DoesNotExist:
        messages.error(request, "Order not found.")
        return redirect('order_history')
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('order_history')

@login_required
@require_http_methods(['POST'])
def update_order_status(request, order_id):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    order = get_object_or_404(Order, id=order_id)
    new_status = request.POST.get('status')
    
    if new_status in [s[0] for s in Order.STATUS_CHOICES]:
        order.status = new_status
        if new_status == 'shipped' and not order.shipped_at:
            order.shipped_at = timezone.now()
        elif new_status == 'delivered' and not order.delivered_at:
            order.delivered_at = timezone.now()
        order.save()
        return JsonResponse({'success': True})
    return JsonResponse({'error': 'Invalid status'}, status=400)

@login_required
@require_POST
def add_tracking_number(request, order_id):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    order = get_object_or_404(Order, id=order_id)
    tracking_number = request.POST.get('tracking_number')
    order.tracking_number = tracking_number
    order.save()
    return JsonResponse({'success': True})


@login_required
def write_review(request, order_item_id):
    order_item = get_object_or_404(OrderItem, id=order_item_id, order__user=request.user)
    reviews = Review.objects.filter(user=request.user, product=order_item.product)
    
    if request.method == 'POST':
        form = ReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.user = request.user
            review.product = order_item.product
            review.save()
            return redirect('order_detail', order_id=order_item.order.id)
    else:
        form = ReviewForm()
    
    return render(request, 'write_review.html', {'form': form, 'order_item': order_item, 'reviews': reviews})


import logging

logger = logging.getLogger(__name__)

@login_required
@login_required
@require_POST
def submit_review(request, order_item_id):
    order_item = get_object_or_404(OrderItem, id=order_item_id, order__user=request.user)
    rating = request.POST.get('rating')
    comment = request.POST.get('comment')
    
    if rating and comment:
        Review.objects.create(
            user=request.user,
            product=order_item.product,
            rating=rating,
            comment=comment
        )
        messages.success(request, 'Your review has been submitted successfully.')
    else:
        messages.error(request, 'Please provide both rating and comment.')
    
    return redirect('order_detail', order_id=order_item.order.id)

@login_required
@require_POST
def delete_review(request, review_id):
    review = get_object_or_404(Review, id=review_id, user=request.user)
    order_id = review.product.orderitem_set.first().order.id
    review.delete()
    messages.success(request, 'Your review has been deleted successfully.')
    return redirect('order_detail', order_id=order_id)


@login_required
def artisan_reviews(request):
    artisan = get_object_or_404(Artisan, user=request.user)
    reviews = Review.objects.filter(product__artisan=artisan).order_by('-created_at')
    
    paginator = Paginator(reviews, 10)  # Show 10 reviews per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    total_reviews = reviews.count()
    average_rating = reviews.aggregate(Avg('rating'))['rating__avg'] or 0

    rating_distribution = {
        5: {'count': reviews.filter(rating=5).count(), 'percentage': 0},
        4: {'count': reviews.filter(rating=4).count(), 'percentage': 0},
        3: {'count': reviews.filter(rating=3).count(), 'percentage': 0},
        2: {'count': reviews.filter(rating=2).count(), 'percentage': 0},
        1: {'count': reviews.filter(rating=1).count(), 'percentage': 0},
    }

    for star, data in rating_distribution.items():
        data['percentage'] = (data['count'] / total_reviews) * 100 if total_reviews > 0 else 0

    context = {
        'reviews': page_obj,
        'average_rating': average_rating,
        'total_reviews': total_reviews,
        'rating_distribution': rating_distribution,
    }

    return render(request, 'artisan_reviews.html', context)

@login_required
def artisan_dashboard(request):
    context = {
        'total_products': Product.objects.filter(artisan=request.user).count(),
        'pending_orders': Order.objects.filter(items__product__artisan=request.user, status='Processing').distinct().count(),
        'total_earnings': Order.objects.filter(items__product__artisan=request.user, status='Delivered').aggregate(Sum('total_price'))['total_price__sum'] or 0,
        'average_rating': Review.objects.filter(product__artisan=request.user).aggregate(Avg('rating'))['rating__avg'] or 0,
        'top_products': Product.objects.filter(artisan=request.user).annotate(sales_count=Count('orderitem')).order_by('-sales_count')[:5],
        'recent_activities': RecentActivity.objects.filter(artisan=request.user).order_by('-timestamp')[:5],
    }
    return render(request, 'artisan.html', context)

@login_required
@user_passes_test(is_delivery_partner)
def delivery_earnings(request):
    # Get the delivery partner profile
    delivery_partner = DeliveryPartner.objects.get(user=request.user)
    
    # Get filter parameters
    date_range = request.GET.get('date_range', 'month')
    transaction_type = request.GET.get('transaction_type', '')
    sort_by = request.GET.get('sort', 'date_desc')
    
    # Calculate earnings for various periods
    today = timezone.now().date()
    first_day_of_month = today.replace(day=1)
    first_day_of_last_month = (first_day_of_month - timezone.timedelta(days=1)).replace(day=1)
    first_day_of_year = today.replace(month=1, day=1)
    
    # Get earnings data
    monthly_earnings = DeliveryEarning.objects.filter(
        delivery__delivery_partner=delivery_partner,
        created_at__gte=first_day_of_month
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    last_month_earnings = DeliveryEarning.objects.filter(
        delivery__delivery_partner=delivery_partner,
        created_at__gte=first_day_of_last_month,
        created_at__lt=first_day_of_month
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    yearly_earnings = DeliveryEarning.objects.filter(
        delivery__delivery_partner=delivery_partner,
        created_at__gte=first_day_of_year
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    # Build filter query for transactions
    query = Q(delivery__delivery_partner=delivery_partner)
    
    # Apply date range filter
    if date_range == 'today':
        query &= Q(created_at__gte=today)
    elif date_range == 'week':
        start_of_week = today - timezone.timedelta(days=today.weekday())
        query &= Q(created_at__gte=start_of_week)
    elif date_range == 'month':
        query &= Q(created_at__gte=first_day_of_month)
    elif date_range == 'year':
        query &= Q(created_at__gte=first_day_of_year)
    
    # Apply transaction type filter
    if transaction_type:
        if transaction_type == 'delivery_fee':
            query &= Q(delivery_fee__gt=0)
        elif transaction_type == 'tip':
            # Assuming tips are stored in a specific way - adjust as needed
            query &= Q(notes__icontains='tip')
        elif transaction_type == 'bonus':
            # Assuming bonuses are stored in a specific way - adjust as needed
            query &= Q(notes__icontains='bonus')
    
    # Apply sorting
    if sort_by == 'date_asc':
        order_by = 'created_at'
    elif sort_by == 'date_desc':
        order_by = '-created_at'
    elif sort_by == 'amount_asc':
        order_by = 'total_amount'
    elif sort_by == 'amount_desc':
        order_by = '-total_amount'
    else:
        order_by = '-created_at'  # Default sort
    
    # Get filtered transactions for the table
    filtered_earnings = DeliveryEarning.objects.filter(query).order_by(order_by)[:50]
    
    transactions = []
    for earning in filtered_earnings:
        transaction = {
            'date': earning.created_at.strftime('%b %d, %Y'),
            'order_id': earning.delivery.order.id if earning.delivery.order else 'N/A',
            'delivery_id': earning.delivery.id,
            'description': f"Delivery earnings for order {earning.delivery.order.id if earning.delivery.order else 'N/A'}",
            'type': 'delivery_fee',  # Default type
            'type_display': 'Delivery Fee',
            'amount': earning.total_amount
        }
        transactions.append(transaction)
    
    context = {
        'monthly_earnings': monthly_earnings,
        'last_month_earnings': last_month_earnings,
        'yearly_earnings': yearly_earnings,
        'transactions': transactions,
        'active_delivery': get_active_delivery(delivery_partner),
        'date_range': date_range,
        'transaction_type': transaction_type,
        'sort_by': sort_by
    }
    
    return render(request, 'delivery_earnings.html', context)

@receiver(post_save, sender=User)
def create_user_cart(sender, instance, created, **kwargs):
    if created:
        Cart.objects.create(user=instance)

def merge_carts(request, user):
    session_cart = request.session.get('cart', {})
    db_cart, created = Cart.objects.get_or_create(user=user)

    for product_id, quantity in session_cart.items():
        product = Product.objects.get(id=product_id)
        cart_item, created = CartItem.objects.get_or_create(cart=db_cart, product=product)
        cart_item.quantity += quantity
        cart_item.save()

    # Clear the session cart
    request.session['cart'] = {}

@login_required
def artisan_blog_write(request):
    if request.method == 'POST':
        if 'blog_id' in request.POST:  # Edit operation
            blog_id = request.POST['blog_id']
            blog = get_object_or_404(Blog, id=blog_id, author=request.user)
            form = BlogForm(request.POST, request.FILES, instance=blog)
            if form.is_valid():
                form.save()
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False, 'error': form.errors})
        else:  # New blog post
            form = BlogForm(request.POST, request.FILES)
            if form.is_valid():
                blog = form.save(commit=False)
                blog.author = request.user
                blog.save()
                messages.success(request, 'Blog post created successfully!')
                return redirect('artisan_blog_write')
            else:
                messages.error(request, 'Error creating blog post. Please check the form.')
    else:
        form = BlogForm()
    
    artisan_blogs = Blog.objects.filter(author=request.user).order_by('-created_at')
    return render(request, 'artisan_blog_write.html', {'form': form, 'artisan_blogs': artisan_blogs})

@login_required
def get_blog_details(request, blog_id):
    blog = get_object_or_404(Blog, id=blog_id, author=request.user)
    return JsonResponse({
        'title': blog.title,
        'content': blog.content,
    })

@login_required
@require_POST
def delete_blog(request, blog_id):
    blog = get_object_or_404(Blog, id=blog_id, author=request.user)
    blog.delete()
    return JsonResponse({'success': True, 'message': 'Blog deleted successfully!'})

def customer_blog_view(request):
    blogs = Blog.objects.all().order_by('-created_at')
    return render(request, 'customer_blog_view.html', {'blogs': blogs})

@login_required
@require_POST
def like_blog(request, blog_id):
    blog = get_object_or_404(Blog, id=blog_id)
    if request.user in blog.likes.all():
        blog.likes.remove(request.user)
        liked = False
    else:
        blog.likes.add(request.user)
        liked = True
    return JsonResponse({'liked': liked, 'likes_count': blog.likes.count()})

@login_required
@require_POST
def add_comment(request, blog_id):
    blog = get_object_or_404(Blog, id=blog_id)
    data = json.loads(request.body)
    content = data.get('content')
    if content:
        comment = Comment.objects.create(blog=blog, user=request.user, content=content)
        return JsonResponse({
            'success': True,
            'comment_id': comment.id,
            'user': comment.user.username,
            'content': comment.content,
            'created_at': comment.created_at.strftime('%B %d, %Y %I:%M %p')
        })
    return JsonResponse({'success': False, 'error': 'Comment content is required.'})

@login_required
@require_POST
def delete_comment(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id, user=request.user)
    comment.delete()
    return JsonResponse({'success': True})

@login_required
@require_GET
def get_blog_comments(request, blog_id):
    blog = get_object_or_404(Blog, id=blog_id)
    comments = blog.comments.all().order_by('-created_at')
    comments_data = [{
        'id': comment.id,
        'user': comment.user.username,
        'content': comment.content,
        'created_at': comment.created_at.strftime('%B %d, %Y %I:%M %p')
    } for comment in comments]
    return JsonResponse({'comments': comments_data})

@login_required
def artisan_documents(request):
    artisan = get_object_or_404(Artisan, user=request.user)
    products = Product.objects.filter(artisan=artisan)
    authenticity_documents = AuthenticityDocument.objects.filter(product__artisan=artisan)

    if request.method == 'POST':
        if 'gst_number' in request.POST:
            artisan.gst_number = request.POST['gst_number']
            if 'gst_certificate' in request.FILES:
                artisan.gst_certificate = request.FILES['gst_certificate']
            artisan.save()
            messages.success(request, 'GST information updated successfully.')
        elif 'product' in request.POST and 'authenticity_document' in request.FILES:
            product = get_object_or_404(Product, id=request.POST['product'], artisan=artisan)
            AuthenticityDocument.objects.create(
                product=product,
                document=request.FILES['authenticity_document']
            )
            messages.success(request, 'Authenticity certificate uploaded successfully.')
        return redirect('artisan_documents')

    context = {
        'artisan': artisan,
        'products': products,
        'authenticity_documents': authenticity_documents,
    }
    return render(request, 'artisan_documents.html', context)

def virtual_try_on(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    return render(request, 'virtual_try_on.html', {'product': product})

@login_required
def download_product_report(request):
    if not request.user.is_staff:
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    # Fetch data
    products = Product.objects.all().select_related('category', 'artisan__user')
    total_products = products.count()
    total_value = products.aggregate(Sum('price'))['price__sum'] or 0
    average_price = products.aggregate(Avg('price'))['price__avg'] or 0

    categories = Category.objects.annotate(product_count=Count('products'))
    
    # Monthly data
    monthly_data = Product.objects.annotate(month=TruncMonth('created_at')).values('month').annotate(
        new_products=Count('id'),
        total_value=Sum('price')
    ).order_by('month')

    # Create a PDF buffer
    buffer = BytesIO()
    
    # Create the PDF object
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', fontSize=24, alignment=1, spaceAfter=0.3*inch)
    heading_style = ParagraphStyle('Heading', fontSize=18, alignment=0, spaceAfter=0.2*inch, spaceBefore=0.3*inch)
    subheading_style = ParagraphStyle('Subheading', fontSize=14, alignment=0, spaceAfter=0.1*inch, spaceBefore=0.2*inch)
    normal_style = styles['Normal']
    
    # Title
    elements.append(Paragraph("Comprehensive Product Report", title_style))
    elements.append(Paragraph(f"Generated on: {timezone.now().strftime('%B %d, %Y')}", normal_style))
    elements.append(Spacer(1, 0.25*inch))
    
    # Overall Summary
    elements.append(Paragraph("Overall Summary", heading_style))
    summary_data = [
        ["Total Products", str(total_products)],
        ["Total Value", f"${total_value:.2f}"],
        ["Average Price", f"${average_price:.2f}"],
    ]
    summary_table = Table(summary_data, colWidths=[2*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(summary_table)
    
    # Category Distribution
    elements.append(Paragraph("Category Distribution", heading_style))
    category_data = [["Category", "Product Count", "Percentage"]]
    for category in categories:
        percentage = (category.product_count / total_products) * 100
        category_data.append([category.name, str(category.product_count), f"{percentage:.2f}%"])
    category_table = Table(category_data, colWidths=[2*inch, 1.5*inch, 1.5*inch])
    category_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(category_table)
    
    # Category Pie Chart
    plt.figure(figsize=(8, 6))
    plt.pie([c.product_count for c in categories], labels=[c.name for c in categories], autopct='%1.1f%%')
    plt.title("Product Distribution by Category")
    img_buffer = BytesIO()
    plt.savefig(img_buffer, format='png')
    img_buffer.seek(0)
    img = Image(img_buffer)
    img.drawHeight = 4*inch
    img.drawWidth = 6*inch
    elements.append(img)
    
    # Monthly Report
    elements.append(Paragraph("Monthly Report", heading_style))
    monthly_table_data = [["Month", "New Products", "Total Value"]]
    for entry in monthly_data:
        monthly_table_data.append([
            entry['month'].strftime("%B %Y"),
            str(entry['new_products']),
            f"${entry['total_value']:.2f}"
        ])
    monthly_table = Table(monthly_table_data, colWidths=[2*inch, 2*inch, 2*inch])
    monthly_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(monthly_table)
    
    # Detailed Product List
    elements.append(Paragraph("Detailed Product List", heading_style))
    product_data = [["ID", "Name", "Category", "Price", "Inventory", "Artisan", "Created At"]]
    for product in products:
        product_data.append([
            str(product.id),
            product.name,
            product.category.name,
            f"${product.price:.2f}",
            str(product.inventory),
            product.artisan.user.username,
            product.created_at.strftime("%Y-%m-%d")
        ])
    product_table = Table(product_data, colWidths=[0.5*inch, 2*inch, 1.5*inch, 1*inch, 1*inch, 1.5*inch, 1.5*inch])
    product_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(product_table)
    
    # Build the PDF
    doc.build(elements)
    
    # FileResponse sets the Content-Disposition header so that browsers
    # present the option to save the file.
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename='product_report.pdf')

@login_required
@require_http_methods(['POST'])
def update_order_status(request, order_id):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    order = get_object_or_404(Order, id=order_id)
    new_status = request.POST.get('status')
    
    if new_status in [s[0] for s in Order.STATUS_CHOICES]:
        order.status = new_status
        if new_status == 'shipped' and not order.shipped_at:
            order.shipped_at = timezone.now()
        elif new_status == 'delivered' and not order.delivered_at:
            order.delivered_at = timezone.now()
        order.save()
        return JsonResponse({'success': True})
    return JsonResponse({'error': 'Invalid status'}, status=400)

@login_required
@require_POST
def add_tracking_number(request, order_id):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    order = get_object_or_404(Order, id=order_id)
    tracking_number = request.POST.get('tracking_number')
    order.tracking_number = tracking_number
    order.save()
    return JsonResponse({'success': True})

@login_required
def simulate_delivery(request, order_id):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id)
        
        try:
            # Update order status to delivered
            order.status = 'delivered'
            order.delivered_at = timezone.now()
            order.save()
            
            # If there's a delivery associated with this order, update it
            try:
                delivery = Delivery.objects.get(order=order)
                delivery.status = 'delivered'
                delivery.actual_delivery_time = timezone.now()
                delivery.save()
                
                # Create delivery status history
                DeliveryStatusHistory.objects.create(
                    delivery=delivery,
                    status='delivered',
                    notes='Delivery completed via simulation',
                    location_lat=delivery.destination_lat,
                    location_lng=delivery.destination_lng
                )
                
                # Update delivery partner status
                delivery_partner = delivery.delivery_partner
                delivery_partner.is_available = True
                delivery_partner.save()
                
                # Create delivery rating placeholder
                DeliveryRating.objects.create(
                    delivery_partner=delivery_partner,
                    delivery=delivery,
                    rating=5,  # Default rating
                    comment="Simulated delivery completed successfully"
                )
                
                # Send notification
                try:
                    send_mail(
                        'Order Delivered Successfully',
                        f'Your order #{order.id} has been delivered successfully.',
                        'noreply@craftsy.com',
                        [order.user.email],
                        fail_silently=True
                    )
                except Exception as e:
                    print(f"Failed to send email notification: {str(e)}")
                
            except Delivery.DoesNotExist:
                # If no delivery exists, create one for record keeping
                delivery_partner = DeliveryPartner.objects.filter(is_available=True).first()
                if delivery_partner:
                    delivery = Delivery.objects.create(
                        order=order,
                        delivery_partner=delivery_partner,
                        status='delivered',
                        delivery_address=f"{order.user.profile.street_address}, {order.user.profile.city}",
                        expected_delivery_time=timezone.now(),
                        actual_delivery_time=timezone.now(),
                        destination_lat=0.0,
                        destination_lng=0.0
                    )
                    
                    DeliveryStatusHistory.objects.create(
                        delivery=delivery,
                        status='delivered',
                        notes='Simulated delivery created and completed',
                        location_lat=0.0,
                        location_lng=0.0
                    )
            
            messages.success(request, f"Order #{order.id} has been successfully delivered (simulated).")
            
        except Exception as e:
            messages.error(request, f"Error simulating delivery: {str(e)}")
            
        return redirect('order_detail', order_id=order.id)
    
    return redirect('order_detail', order_id=order.id)

@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_delivery_partners(request):
    """Admin view for managing delivery partners."""
    # Handle form submissions for approving/rejecting partners
    if request.method == 'POST':
        partner_id = request.POST.get('partner_id')
        action = request.POST.get('action')
        
        if partner_id and action in ['approve', 'reject']:
            partner = get_object_or_404(DeliveryPartner, id=partner_id)
            
            if action == 'approve':
                partner.status = 'approved'
                partner.is_available = True
                messages.success(request, f"Delivery partner {partner.user.get_full_name()} has been approved.")
                
                # Create notification for the partner
                Notification.objects.create(
                    user=partner.user,
                    title='Account Approved',
                    message='Your delivery partner account has been approved. You can now start accepting deliveries.'
                )
            
            elif action == 'reject':
                partner.status = 'rejected'
                partner.is_available = False
                messages.success(request, f"Delivery partner {partner.user.get_full_name()} has been rejected.")
                
                # Create notification for the partner
                Notification.objects.create(
                    user=partner.user,
                    title='Account Rejected',
                    message='Your delivery partner application has been rejected. Please contact admin for more information.'
                )
            
            partner.save()
            return redirect('admin_delivery_partners')
    
    # Get all partners with status counts
    partners = DeliveryPartner.objects.select_related('user')
    
    # Calculate metrics for each partner
    for partner in partners:
        partner.total_deliveries = Delivery.objects.filter(delivery_partner=partner).count()
        partner.completed_deliveries = Delivery.objects.filter(
            delivery_partner=partner, 
            status='delivered'
        ).count()
        
        # Check if partner has active deliveries despite being marked as available
        partner.active_deliveries = Delivery.objects.filter(
            delivery_partner=partner,
            status__in=['pending', 'picked_up', 'in_transit', 'out_for_delivery']
        ).count()
        
        # Fix partner availability status based on active deliveries
        if partner.status == 'approved':
            if partner.active_deliveries > 0:
                # Partner has active deliveries, should be marked as busy
                if partner.is_available:
                    partner.is_available = False
                    partner.save()
            else:
                # Partner has no active deliveries, should be marked as available
                if not partner.is_available:
                    partner.is_available = True
                    partner.save()
        
        # Flag inconsistent status
        partner.status_inconsistent = (partner.is_available and partner.active_deliveries > 0) or \
                                      (not partner.is_available and partner.active_deliveries == 0 and partner.status == 'approved')
        
        # Get current active delivery if any
        partner.current_delivery = Delivery.objects.filter(
            delivery_partner=partner,
            status__in=['pending', 'picked_up', 'in_transit', 'out_for_delivery']
        ).first()
        
        # Calculate success rate if any deliveries
        if partner.total_deliveries > 0:
            partner.success_rate = (partner.completed_deliveries / partner.total_deliveries) * 100
        else:
            partner.success_rate = 0
    
    # Filter partners by status if requested
    status_filter = request.GET.get('status')
    if status_filter:
        partners = [p for p in partners if p.status == status_filter]
    
    # Create lists for the template
    pending_partners_list = [p for p in partners if p.status == 'pending']
    active_partners_list = [p for p in partners if p.status == 'approved']
    
    context = {
        'partners': partners,
        'pending_count': sum(1 for p in partners if p.status == 'pending'),
        'approved_count': sum(1 for p in partners if p.status == 'approved'),
        'suspended_count': sum(1 for p in partners if p.status == 'suspended'),
        'rejected_count': sum(1 for p in partners if p.status == 'rejected'),
        'available_count': sum(1 for p in partners if p.is_available and p.status == 'approved'),
        'busy_count': sum(1 for p in partners if not p.is_available and p.status == 'approved'),
        'inconsistent_count': sum(1 for p in partners if p.status_inconsistent),
        # Add these variables for the template
        'total_partners': len(partners),
        'pending_partners': len(pending_partners_list),
        'active_partners': len(active_partners_list),
        'pending_partners_list': pending_partners_list,
        'active_partners_list': active_partners_list
    }
    
    return render(request, 'admin_delivery_partners.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_delivery_partner_details(request, partner_id):
    partner = get_object_or_404(DeliveryPartner, id=partner_id)
    
    # Get partner's delivery history
    deliveries = Delivery.objects.filter(delivery_partner=partner)
    
    # Calculate statistics
    total_deliveries = deliveries.count()
    completed_deliveries = deliveries.filter(status='delivered').count()
    on_time_deliveries = deliveries.filter(
        status='delivered',
        actual_delivery_time__lte=F('expected_delivery_time')
    ).count()
    
    on_time_percentage = (on_time_deliveries / completed_deliveries * 100) if completed_deliveries > 0 else 0
    
    # Get ratings for deliveries made by this partner
    ratings = DeliveryRating.objects.filter(
        delivery__in=deliveries
    ).order_by('-created_at')[:10]
    
    context = {
        'partner': partner,
        'total_deliveries': total_deliveries,
        'completed_deliveries': completed_deliveries,
        'on_time_percentage': round(on_time_percentage, 2),
        'recent_deliveries': deliveries.order_by('-created_at')[:10],
        'ratings': ratings,
    }
    return render(request, 'admin_delivery_partner_details.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff)
@require_POST
def suspend_delivery_partner(request, partner_id):
    partner = get_object_or_404(DeliveryPartner, id=partner_id)
    try:
        partner.status = 'suspended'
        partner.is_available = False
        partner.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@user_passes_test(lambda u: u.is_staff)
@require_POST
def reactivate_delivery_partner(request, partner_id):
    partner = get_object_or_404(DeliveryPartner, id=partner_id)
    try:
        partner.status = 'approved'
        partner.is_available = True
        partner.save()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@user_passes_test(is_delivery_partner)
@require_POST
def update_delivery_status(request, delivery_id):
    try:
        delivery = get_object_or_404(
            Delivery.objects.select_related('delivery_partner', 'order__user'),
            id=delivery_id,
            delivery_partner=request.user.delivery_partner
        )
        
        status = request.POST.get('status')
        notes = request.POST.get('notes', '')
        
        if status not in dict(Delivery.STATUS_CHOICES):
            return JsonResponse({'success': False, 'error': 'Invalid status'}, status=400)
        
        old_status = delivery.status
        delivery.status = status
        
        if status == 'delivered':
            delivery.actual_delivery_time = timezone.now()
            delivery.delivery_partner.is_available = True
            delivery.delivery_partner.save()
        
        delivery.save()
        
        # Create status history entry efficiently
        DeliveryStatusHistory.objects.create(
            delivery=delivery,
            status=status,
            notes=notes,
            location_lat=delivery.delivery_partner.current_location_lat,
            location_lng=delivery.delivery_partner.current_location_lng
        )
        
        # Create notification for customer
        if old_status != status:
            Notification.objects.create(
                user=delivery.order.user,
                title='Delivery Status Update - Order #{delivery.order.id}',
                message=f'Your delivery status has been updated to: {status.title()}',
                notification_type='delivery_update',
                reference_id=delivery.id
            )
        
        return JsonResponse({
            'success': True,
            'delivery_id': delivery_id,
            'new_status': status,
            'updated_at': timezone.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error updating delivery status: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@user_passes_test(is_delivery_partner)
@require_POST
def mark_delivery_delivered(request, delivery_id):
    try:
        # First try to get the delivery for the current user (whether staff or delivery partner)
        if request.user.is_staff:
            delivery = get_object_or_404(Delivery, id=delivery_id)
        else:
            delivery = get_object_or_404(Delivery, id=delivery_id, delivery_partner__user=request.user)
        
        with transaction.atomic():
            # Update delivery status
            delivery.status = 'delivered'
            delivery.actual_delivery_time = timezone.now()
            delivery.save()
            
            # Update order status
            delivery.order.status = 'delivered'
            delivery.order.save()
            
            # Mark delivery partner as available
            delivery_partner = delivery.delivery_partner
            delivery_partner.is_available = True
            delivery_partner.save()
            
            # Create status history
            DeliveryStatusHistory.objects.create(
                delivery=delivery,
                status='delivered',
                notes='Delivery completed successfully'
            )
            
            # Create notification for customer
            Notification.objects.create(
                user=delivery.order.user,
                title=f'Order #{delivery.order.id} Delivered',
                message='Your order has been delivered successfully!'
            )
            
            # Create notification for rating
            Notification.objects.create(
                user=delivery.order.user,
                title=f'Rate Your Delivery',
                message=f'Please rate your delivery experience for order #{delivery.order.id}'
            )
            
            # Process delivery earnings if applicable
            try:
                process_delivery_earnings(request, delivery.id)
            except Exception as e:
                logger.error(f"Error processing earnings: {str(e)}")
            
            messages.success(request, 'Delivery marked as delivered successfully.')
            
            if request.is_ajax():
                return JsonResponse({'success': True})
            
            if request.user.is_staff:
                return redirect('admin_delivery_dashboard')
            else:
                return redirect('delivery_dashboard')
                
    except Exception as e:
        messages.error(request, f'Error marking delivery as delivered: {str(e)}')
        if request.is_ajax():
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
            
        if request.user.is_staff:
            return redirect('admin_delivery_dashboard')
        else:
            return redirect('delivery_dashboard')

@login_required
@user_passes_test(is_delivery_partner)
def get_delivery_location(request, delivery_id):
    delivery = get_object_or_404(Delivery, id=delivery_id)
    partner = delivery.delivery_partner
    
    return JsonResponse({
        'success': True,
        'latitude': float(partner.current_location_lat),
        'longitude': float(partner.current_location_lng)
    })

@login_required
@user_passes_test(is_delivery_partner)
def get_delivery_route(request, delivery_id):
    delivery = get_object_or_404(Delivery, id=delivery_id)
    route_points = delivery.route_points.all()
    
    route = [{
        'lat': float(point.latitude),
        'lng': float(point.longitude),
        'timestamp': point.timestamp.isoformat()
    } for point in route_points]
    
    return JsonResponse({
        'success': True,
        'route': route
    })

@login_required
@user_passes_test(is_delivery_partner)
def export_delivery_history(request):
    delivery_partner = request.user.delivery_partner
    deliveries = Delivery.objects.filter(delivery_partner=delivery_partner)
    
    # Create the HttpResponse object with PDF header
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="delivery_history.pdf"'
    
    # Create the PDF object
    doc = SimpleDocTemplate(response, pagesize=letter)
    elements = []
    
    # Add content to the PDF
    styles = getSampleStyleSheet()
    elements.append(Paragraph(f"Delivery History - {delivery_partner.user.get_full_name()}", styles['Title']))
    elements.append(Spacer(1, 12))
    
    # Create table data
    data = [['Order ID', 'Customer', 'Date', 'Status', 'Delivery Time', 'Amount']]
    for delivery in deliveries:
        data.append([
            f"#{delivery.order.id}",
            delivery.order.user.get_full_name(),
            delivery.created_at.strftime("%Y-%m-%d"),
            delivery.get_status_display(),
            str(delivery.get_delivery_time()) + ' hours' if delivery.get_delivery_time() else 'N/A',
            f"₹{delivery.order.total_price}"
        ])
    
    # Create and style the table
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
    ]))
    
    elements.append(table)
    doc.build(elements)
    return response

def delivery_partner_register(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                user = form.save(commit=False)
                user.user_type = 'delivery_partner'
                user.save()
                
                # Create DeliveryPartner profile
                delivery_partner = DeliveryPartner.objects.create(
                    user=user,
                    vehicle_type=request.POST.get('vehicle_type', ''),
                    vehicle_number=request.POST.get('vehicle_number', ''),
                    license_number=request.POST.get('license_number', ''),
                    license_image=request.FILES.get('license_image'),
                    id_proof=request.FILES.get('id_proof'),
                    status='pending'  # Set initial status as pending
                )
                
                # Notify admin about new delivery partner registration
                admin_users = User.objects.filter(is_staff=True)
                for admin in admin_users:
                    Notification.objects.create(
                        user=admin,
                        title='New Delivery Partner Registration',
                        message=f'New delivery partner registration from {user.get_full_name()}. Please review and approve.',
                        notification_type='delivery_partner_registration',
                        reference_id=delivery_partner.id
                    )
            
            messages.success(request, 'Registration successful. Please wait for admin approval. You will be notified once your application is reviewed.')
            return redirect('login')
    else:
        form = UserRegistrationForm()
    
    return render(request, 'delivery_partner_register.html', {'form': form})

@login_required
@user_passes_test(is_delivery_partner)
def delivery_profile(request):
    delivery_partner = get_object_or_404(DeliveryPartner, user=request.user)
    
    if request.method == 'POST':
        try:
            # Update basic user info
            request.user.first_name = request.POST.get('first_name')
            request.user.last_name = request.POST.get('last_name')
            request.user.email = request.POST.get('email')
            request.user.save()
            
            # Update delivery partner specific info
            delivery_partner.phone_number = request.POST.get('phone_number')
            delivery_partner.vehicle_type = request.POST.get('vehicle_type')
            delivery_partner.vehicle_number = request.POST.get('vehicle_number')
            delivery_partner.license_number = request.POST.get('license_number')
            
            # Handle file uploads
            if 'profile_picture' in request.FILES:
                if delivery_partner.profile_picture:
                    delivery_partner.profile_picture.delete(save=False)
                delivery_partner.profile_picture = request.FILES['profile_picture']
            
            # Handle other document uploads
            for field in ['license_image', 'id_proof', 'vehicle_registration', 'insurance_document']:
                if field in request.FILES:
                    if getattr(delivery_partner, field):
                        getattr(delivery_partner, field).delete(save=False)
                    setattr(delivery_partner, field, request.FILES[field])
            
            # If documents are updated, set status back to pending for admin review
            if any(key in request.FILES for key in ['license_image', 'id_proof', 'vehicle_registration', 'insurance_document']):
                delivery_partner.status = 'pending'
                messages.info(request, 'Your documents have been submitted for review.')
            
            delivery_partner.save()
            messages.success(request, 'Profile updated successfully!')
            return redirect('delivery_profile')
            
        except Exception as e:
            messages.error(request, f'Error updating profile: {str(e)}')
    
    context = {
        'delivery_partner': delivery_partner,
        'total_deliveries': Delivery.objects.filter(delivery_partner=delivery_partner).count(),
        'completed_deliveries': Delivery.objects.filter(
            delivery_partner=delivery_partner,
            status='delivered'
        ).count(),
        'total_earnings': Delivery.objects.filter(
            delivery_partner=delivery_partner,
            status='delivered'
        ).aggregate(Sum('order__total_price'))['order__total_price__sum'] or 0,
        'active_delivery': get_active_delivery(delivery_partner)
    }
    return render(request, 'delivery_profile.html', context)

@login_required
@user_passes_test(is_delivery_partner)
def delivery_earnings(request):
    # Get the delivery partner profile
    delivery_partner = DeliveryPartner.objects.get(user=request.user)
    
    # Calculate earnings for various periods
    today = timezone.now().date()
    first_day_of_month = today.replace(day=1)
    first_day_of_last_month = (first_day_of_month - timezone.timedelta(days=1)).replace(day=1)
    first_day_of_year = today.replace(month=1, day=1)
    
    # Get earnings data
    monthly_earnings = DeliveryEarning.objects.filter(
        delivery__delivery_partner=delivery_partner,
        created_at__gte=first_day_of_month
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    last_month_earnings = DeliveryEarning.objects.filter(
        delivery__delivery_partner=delivery_partner,
        created_at__gte=first_day_of_last_month,
        created_at__lt=first_day_of_month
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    yearly_earnings = DeliveryEarning.objects.filter(
        delivery__delivery_partner=delivery_partner,
        created_at__gte=first_day_of_year
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    # Get transactions for the table
    transactions = []
    earnings = DeliveryEarning.objects.filter(
        delivery__delivery_partner=delivery_partner
    ).order_by('-created_at')[:50]
    
    for earning in earnings:
        transaction = {
            'date': earning.created_at.strftime('%b %d, %Y'),
            'order_id': earning.delivery.order.id if earning.delivery.order else 'N/A',
            'delivery_id': earning.delivery.id,
            'description': f"Delivery earnings for order {earning.delivery.order.id if earning.delivery.order else 'N/A'}",
            'type': 'delivery_fee',  # Default type
            'type_display': 'Delivery Fee',
            'amount': earning.total_amount
        }
        transactions.append(transaction)
    
    context = {
        'monthly_earnings': monthly_earnings,
        'last_month_earnings': last_month_earnings,
        'yearly_earnings': yearly_earnings,
        'transactions': transactions,
        'active_delivery': get_active_delivery(delivery_partner)
    }
    
    return render(request, 'delivery_earnings.html', context)

@login_required
@user_passes_test(is_delivery_partner)
def export_earnings(request):
    """Export earnings data as CSV file for download"""
    # Get the delivery partner profile
    delivery_partner = DeliveryPartner.objects.get(user=request.user)
    
    # Get filter parameters
    date_range = request.GET.get('date_range', 'month')
    transaction_type = request.GET.get('transaction_type', '')
    today = timezone.now().date()
    
    # Set date range based on parameter
    if date_range == 'today':
        start_date = today
    elif date_range == 'week':
        start_date = today - timezone.timedelta(days=today.weekday())
    elif date_range == 'month':
        start_date = today.replace(day=1)
    elif date_range == 'year':
        start_date = today.replace(month=1, day=1)
    elif date_range == 'all':
        start_date = None
    else:
        start_date = today.replace(day=1)  # Default to current month
    
    # Build query based on filters
    query = Q(delivery__delivery_partner=delivery_partner)
    if start_date:
        query &= Q(created_at__gte=start_date)
    
    # Add transaction type filter if specified
    if transaction_type:
        if transaction_type == 'delivery_fee':
            query &= Q(delivery_fee__gt=0)
        elif transaction_type == 'tip':
            # Assuming tips are stored in a specific way - adjust as needed
            query &= Q(notes__icontains='tip')
        elif transaction_type == 'bonus':
            # Assuming bonuses are stored in a specific way - adjust as needed
            query &= Q(notes__icontains='bonus')
    
    earnings = DeliveryEarning.objects.filter(query).order_by('-created_at')
    
    # Create the HttpResponse object with CSV header
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="earnings_export_{today.strftime("%Y%m%d")}.csv"'
    
    # Create CSV writer
    writer = csv.writer(response)
    writer.writerow(['Date', 'Order ID', 'Description', 'Base Amount', 'Delivery Fee', 'Total Amount (₹)'])
    
    # Add data to CSV
    for earning in earnings:
        writer.writerow([
            earning.created_at.strftime('%Y-%m-%d %H:%M'),
            earning.delivery.order.id if earning.delivery.order else 'N/A',
            f"Delivery earnings for order {earning.delivery.order.id if earning.delivery.order else 'N/A'}",
            earning.base_amount,
            earning.delivery_fee,
            earning.total_amount
        ])
    
    return response

@login_required
@user_passes_test(is_delivery_partner)
def process_delivery_earnings(request, delivery_id):
    """Process earnings for a completed delivery."""
    try:
        delivery = get_object_or_404(
            Delivery.objects.select_related('order', 'delivery_partner'),
            id=delivery_id,
            delivery_partner=request.user.delivery_partner,
            status='delivered'
        )
        
        with transaction.atomic():
            order_total = float(delivery.order.total_price)
            
            # Calculate profit shares
            artisan_share = order_total * 0.70  # 70% to artisan
            platform_fee = order_total * 0.10   # 10% platform fee
            delivery_share = order_total * 0.20  # 20% to delivery partner
            
            # Calculate delivery fees
            base_delivery_fee = 50  # Base delivery fee
            delivery_time = delivery.get_delivery_time() or 0
            distance_fee = delivery_time * 10  # ₹10 per hour
            total_delivery_fee = base_delivery_fee + distance_fee
            
            # Total earnings for this delivery
            total_earnings = delivery_share + total_delivery_fee
            
            # Create earnings record
            DeliveryEarning.objects.create(
                delivery=delivery,
                delivery_partner=delivery.delivery_partner,
                base_amount=delivery_share,
                delivery_fee=total_delivery_fee,
                total_amount=total_earnings,
                artisan_share=artisan_share,
                platform_fee=platform_fee,
                status='processed'
            )
            
            # Create notification
            Notification.objects.create(
                user=delivery.delivery_partner.user,
                title='Earnings Processed',
                message=f'Your earnings for order #{delivery.order.id} have been processed. Total: ₹{total_earnings:.2f}',
                notification_type='earnings'
            )
            
            # Update delivery partner's balance
            delivery_partner = delivery.delivery_partner
            delivery_partner.balance += total_earnings
            delivery_partner.save()
            
            return JsonResponse({
                'success': True,
                'message': 'Earnings processed successfully',
                'earnings': {
                    'base_amount': delivery_share,
                    'delivery_fee': total_delivery_fee,
                    'total_earnings': total_earnings
                }
            })
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@user_passes_test(lambda u: u.is_staff)
def pending_delivery_partners(request):
    # Get all pending partners with related user data
    partners = DeliveryPartner.objects.filter(status='pending').select_related('user')
    
    # Add additional context for each partner
    for partner in partners:
        partner.full_name = partner.user.get_full_name()
        partner.email = partner.user.email
        partner.registration_date = partner.user.date_joined
    
    context = {
        'partners': partners,
        'pending_count': partners.count(),
        'page_title': 'Pending Delivery Partner Applications',
        'section': 'delivery_partners'
    }
    return render(request, 'admin/pending_delivery_partners.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff)
def approve_delivery_partner(request, partner_id):
    partner = get_object_or_404(DeliveryPartner, id=partner_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'approve':
            partner.status = 'approved'
            partner.is_available = True  # Set availability to True when approved
            messages.success(request, f'Delivery partner {partner.user.get_full_name()} has been approved.')
            
            # Create notification for the delivery partner
            Notification.objects.create(
                user=partner.user,
                title='Account Approved',
                message='Your delivery partner account has been approved. You can now start accepting deliveries.'
            )
        elif action == 'reject':
            partner.status = 'rejected'
            partner.is_available = False
            messages.warning(request, f'Delivery partner {partner.user.get_full_name()} has been rejected.')
            
            # Create notification for the delivery partner
            Notification.objects.create(
                user=partner.user,
                title='Account Rejected',
                message='Your delivery partner account application has been rejected. Please contact admin for more information.'
            )
        partner.save()
    return redirect('pending_delivery_partners')

@login_required
@user_passes_test(lambda u: u.is_staff)
def assign_delivery(request, order_id):
    """View to assign a delivery partner to an order."""
    order = get_object_or_404(Order, id=order_id)
    
    if request.method == 'POST':
        delivery_partner_id = request.POST.get('delivery_partner')
        if delivery_partner_id:
            try:
                with transaction.atomic():
                    delivery_partner = DeliveryPartner.objects.get(id=delivery_partner_id)
                    
                    # Create delivery record
                    delivery = Delivery.objects.create(
                        order=order,
                        delivery_partner=delivery_partner,
                        status='pending',
                        expected_delivery_time=timezone.now() + timedelta(days=3)
                    )
                    
                    # Create initial status history
                    DeliveryStatusHistory.objects.create(
                        delivery=delivery,
                        status='pending',
                        notes='Delivery assigned to partner'
                    )
                    
                    # Update order status
                    order.status = 'in_transit'
                    order.save()
                    
                    # Create notifications
                    Notification.objects.create(
                        user=delivery_partner.user,
                        title='New Delivery Assignment',
                        message=f'You have been assigned to deliver order #{order.id}'
                    )
                    
                    Notification.objects.create(
                        user=order.user,
                        title='Order Update',
                        message=f'Your order #{order.id} has been assigned for delivery'
                    )
                    
                    messages.success(request, 'Delivery partner assigned successfully')
                    return redirect('unassigned_orders')
            except Exception as e:
                messages.error(request, f'Error assigning delivery partner: {str(e)}')
                return redirect('assign_delivery', order_id=order_id)
    
    # Get available delivery partners
    available_partners = DeliveryPartner.objects.filter(
        status='approved'
    ).annotate(
        active_deliveries=Count('deliveries', filter=Q(deliveries__status__in=['pending', 'in_transit']))
    ).filter(active_deliveries__lt=3)  # Limit to partners with less than 3 active deliveries
    
    context = {
        'order': order,
        'delivery_partners': available_partners,
        'page_title': f'Assign Delivery - Order #{order.id}'
    }
    return render(request, 'assign_delivery.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff)
@require_POST
def handle_authenticity_document(request, document_id, action):
    try:
        document = get_object_or_404(AuthenticityDocument, id=document_id)
        if action == 'verify':
            document.is_verified = True
            message = 'Document verified successfully.'
        elif action == 'reject':
            document.is_verified = False
            message = 'Document rejected successfully.'
        else:
            return JsonResponse({'success': False, 'message': 'Invalid action.'}, status=400)
        document.save()
        return JsonResponse({'success': True, 'message': message})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required
def chat_room(request, room_name):
    messages = ChatMessage.objects.filter(thread_name=room_name).order_by('timestamp')
    
    if request.user.user_type == 'artisan':
        template = 'artisan_chat_room.html'
    else:
        template = 'customer_chat_room.html'
    
    return render(request, template, {
        'room_name': room_name,
        'messages': messages
    })

@login_required
def get_messages(request, room_name):
    try:
        last_id = int(request.GET.get('last_id', 0))
        messages = ChatMessage.objects.filter(thread_name=room_name, id__gt=last_id).order_by('timestamp')
        return JsonResponse({
            'success': True,
            'messages': [
                {
                    'id': msg.id,
                    'username': msg.user.username,
                    'message': msg.message,
                    'timestamp': msg.timestamp.isoformat(),
                    'user_type': msg.user.user_type
                }
                for msg in messages
            ]
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@csrf_exempt
def send_message(request, room_name):
    if request.method == 'POST':
        try:
            message = request.POST.get('message')
            if not message:
                return JsonResponse({'success': False, 'error': 'Message content is required.'}, status=400)
            
            new_message = ChatMessage.objects.create(
                user=request.user,
                thread_name=room_name,
                message=message,
                timestamp=timezone.now()
            )
            return JsonResponse({
                'success': True,
                'id': new_message.id,
                'timestamp': new_message.timestamp.isoformat(),
                'user_type': request.user.user_type
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)
    return JsonResponse({'success': False, 'error': 'Invalid request method.'}, status=405)

@login_required
@require_POST
def clear_chat(request, room_name):
    try:
        ChatMessage.objects.filter(thread_name=room_name).delete()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def download_invoice(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    
    if order.status != 'delivered':
        messages.error(request, "Invoice is only available for delivered orders.")
        return redirect('order_detail', order_id=order.id)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('Center', alignment=1))
    styles.add(ParagraphStyle('Right', alignment=2))

    # Header
    elements.append(Paragraph("Craftsy", styles['Title']))
    elements.append(Paragraph("Handmade with love", styles['Italic']))
    elements.append(Spacer(1, 0.25*inch))

    # Invoice details
    invoice_data = [
        ['Invoice No:', f'INV-{order.id:06d}'],
        ['Date:', order.created_at.strftime('%B %d, %Y')],
        ['Order Status:', order.get_status_display()],
    ]
    invoice_table = Table(invoice_data, colWidths=[1.5*inch, 4*inch])
    invoice_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
    ]))
    elements.append(invoice_table)
    elements.append(Spacer(1, 0.25*inch))

    # Customer details
    elements.append(Paragraph("Bill To:", styles['Heading3']))
    customer_data = [
        [order.user.get_full_name()],
        [order.user.email],
        # Add any other available customer information here
    ]
    customer_table = Table(customer_data)
    customer_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(customer_table)
    elements.append(Spacer(1, 0.25*inch))

    # Order items
    elements.append(Paragraph("Order Details", styles['Heading3']))
    data = [['Product', 'Artisan', 'Quantity', 'Unit Price', 'Total']]
    for item in order.items.all():
        data.append([
            item.product.name,
            item.product.artisan.user.get_full_name(),
            str(item.quantity),
            f"${item.price:.2f}",
            f"${item.price * item.quantity:.2f}"
        ])
    
    # Total
    data.append(['', '', '', 'Total:', f"${order.total_price:.2f}"])

    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
    ]))
    elements.append(table)

    # Thank you message
    elements.append(Spacer(1, 0.5*inch))
    elements.append(Paragraph("Thank you for your purchase!", styles['Center']))
    elements.append(Paragraph("We appreciate your support for our artisans.", styles['Center']))

    # Footer
    def add_page_number(canvas, doc):
        page_num = canvas.getPageNumber()
        text = f"Page {page_num}"
        canvas.drawRightString(7.5*inch, 0.75*inch, text)

    doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)

    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename=f'invoice_order_{order.id}.pdf')

@login_required
@user_passes_test(lambda u: u.is_staff)
@require_POST
def handle_authenticity_document(request, document_id, action):
    try:
        document = get_object_or_404(AuthenticityDocument, id=document_id)
        if action == 'verify':
            document.is_verified = True
            message = 'Document verified successfully.'
        elif action == 'reject':
            document.is_verified = False
            message = 'Document rejected successfully.'
        else:
            return JsonResponse({'success': False, 'message': 'Invalid action.'}, status=400)
        document.save()
        return JsonResponse({'success': True, 'message': message})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

@login_required
def download_earnings_report(request):
    artisan = request.user.artisan
    
    # Date range for the report (last 12 months)
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=365)
    
    # Fetch data
    completed_orders = Order.objects.filter(
        items__product__artisan=artisan, 
        status='delivered',
        created_at__range=[start_date, end_date]
    ).distinct()
    
    products = Product.objects.filter(artisan=artisan)
    
    # Create a PDF buffer
    buffer = BytesIO()
    
    # Create the PDF object
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', fontSize=24, alignment=1, spaceAfter=12)
    heading_style = ParagraphStyle('Heading', fontSize=18, alignment=0, spaceAfter=6, spaceBefore=12)
    normal_style = styles['Normal']
    
    # Title
    elements.append(Paragraph("Detailed Artisan Earnings Report", title_style))
    elements.append(Paragraph(f"Generated on: {timezone.now().strftime('%B %d, %Y')}", normal_style))
    elements.append(Paragraph(f"Artisan: {artisan.user.get_full_name()}", normal_style))
    elements.append(Paragraph(f"Email: {artisan.user.email}", normal_style))
    elements.append(Spacer(1, 0.25*inch))
    
    # Overall Summary
    elements.append(Paragraph("Overall Summary", heading_style))
    total_earnings = completed_orders.aggregate(Sum('total_price'))['total_price__sum'] or 0
    total_orders = completed_orders.count()
    average_order_value = total_earnings / total_orders if total_orders > 0 else 0
    
    summary_data = [
        ["Total Earnings", f"${total_earnings:.2f}"],
        ["Total Orders", str(total_orders)],
        ["Average Order Value", f"${average_order_value:.2f}"],
    ]
    summary_table = Table(summary_data, colWidths=[3*inch, 3*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.25*inch))
    
    # Monthly Earnings Breakdown
    elements.append(Paragraph("Monthly Earnings Breakdown", heading_style))
    monthly_earnings = completed_orders.annotate(month=TruncMonth('created_at')).values('month').annotate(
        earnings=Sum('total_price'),
        orders=Count('id')
    ).order_by('month')
    
    monthly_data = [["Month", "Earnings", "Orders"]]
    for entry in monthly_earnings:
        monthly_data.append([
            entry['month'].strftime("%B %Y"),
            f"${entry['earnings']:.2f}",
            str(entry['orders'])
        ])
    
    monthly_table = Table(monthly_data, colWidths=[2*inch, 2*inch, 2*inch])
    monthly_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(monthly_table)
    elements.append(Spacer(1, 0.25*inch))
    
    # Product Performance
    elements.append(Paragraph("Product Performance", heading_style))
    product_performance = products.annotate(
        total_sales=Sum('orderitem__price'),
        units_sold=Sum('orderitem__quantity')
    ).order_by('-total_sales')
    
    product_data = [["Product", "Total Sales", "Units Sold", "Avg. Price"]]
    for product in product_performance:
        avg_price = product.total_sales / product.units_sold if product.units_sold else 0
        product_data.append([
            product.name,
            f"${product.total_sales:.2f}" if product.total_sales else "$0.00",
            str(product.units_sold or 0),
            f"${avg_price:.2f}"
        ])
    
    product_table = Table(product_data, colWidths=[2*inch, 1.5*inch, 1.5*inch, 1.5*inch])
    product_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(product_table)
    elements.append(Spacer(1, 0.25*inch))
    
    # Recent Orders
    elements.append(Paragraph("Recent Orders (Last 10)", heading_style))
    recent_orders = completed_orders.order_by('-created_at')[:10]
    
    order_data = [["Order ID", "Date", "Total", "Items"]]
    for order in recent_orders:
        items = ", ".join([f"{item.product.name} (x{item.quantity})" for item in order.items.all()])
        order_data.append([
            str(order.id),
            order.created_at.strftime("%Y-%m-%d"),
            f"${order.total_price:.2f}",
            items
        ])
    
    order_table = Table(order_data, colWidths=[1*inch, 1.5*inch, 1.5*inch, 3.5*inch])
    order_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(order_table)
    
    # Build the PDF
    doc.build(elements)
    
    # FileResponse sets the Content-Disposition header so that browsers
    # present the option to save the file.
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/pdf')

@login_required
@user_passes_test(is_delivery_partner)
def delivery_dashboard(request):
    try:
        delivery_partner = request.user.delivery_partner
        
        # Get all active deliveries
        active_deliveries = get_active_delivery(delivery_partner)
        
        # Get all completed deliveries
        completed_deliveries = Delivery.objects.filter(
            delivery_partner=delivery_partner,
            status='delivered'
        ).order_by('-actual_delivery_time')
        
        ratings = DeliveryRating.objects.filter(
            delivery__in=completed_deliveries
        ).select_related('user', 'delivery')
        
        avg_rating = delivery_partner.rating if hasattr(delivery_partner, 'rating') else 0
        
        context = {
            'active_deliveries': active_deliveries,  # Changed from active_delivery to active_deliveries
            'active_delivery_count': active_deliveries.count(),  # Add count for template use
            'completed_deliveries': completed_deliveries,
            'ratings': ratings,
            'avg_rating': avg_rating,
            'total_deliveries': completed_deliveries.count(),
            'recent_notifications': Notification.objects.filter(user=request.user).order_by('-created_at')[:5],
            'unread_notifications_count': Notification.objects.filter(user=request.user, is_read=False).count()
        }
        return render(request, 'delivery_dashboard.html', context)
    except DeliveryPartner.DoesNotExist:
        messages.error(request, 'You are not registered as a delivery partner.')
        return redirect('home')

@login_required
@user_passes_test(is_delivery_partner)
def delivery_history(request):
    try:
        delivery_partner = request.user.delivery_partner
        
        # Get all deliveries for this partner
        deliveries = Delivery.objects.filter(
            delivery_partner=delivery_partner
        ).order_by('-actual_delivery_time')
        
        # Filter by status if provided
        status_filter = request.GET.get('status')
        if status_filter:
            deliveries = deliveries.filter(status=status_filter)
        
        # Filter by date range if provided
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        if start_date and end_date:
            try:
                start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d')
                end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d')
                deliveries = deliveries.filter(created_at__range=[start_date, end_date])
            except ValueError:
                messages.error(request, 'Invalid date format. Please use YYYY-MM-DD.')
        
        # Calculate statistics
        total_deliveries = deliveries.count()
        completed_deliveries = deliveries.filter(status='delivered').count()
        total_earnings = DeliveryEarning.objects.filter(
            delivery_partner=delivery_partner,
            delivery__status='delivered'
        ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        
        # Get delivery ratings
        ratings = DeliveryRating.objects.filter(
            delivery__delivery_partner=delivery_partner
        ).select_related('delivery', 'user')
        
        context = {
            'deliveries': deliveries,
            'total_deliveries': total_deliveries,
            'completed_deliveries': completed_deliveries,
            'total_earnings': total_earnings,
            'ratings': ratings,
            'status_filter': status_filter,
            'start_date': start_date,
            'end_date': end_date
        }
        
        return render(request, 'delivery_history.html', context)
    except DeliveryPartner.DoesNotExist:
        messages.error(request, 'You are not registered as a delivery partner.')
        return redirect('home')

@login_required
@user_passes_test(is_delivery_partner)
def delivery_tracking(request, delivery_id):
    # Get the delivery
    delivery = get_object_or_404(Delivery, id=delivery_id)
    
    # Check if user has permission to view this delivery
    if not (request.user.is_staff or 
            (hasattr(delivery.order, 'user') and request.user == delivery.order.user) or 
            (delivery.delivery_partner and hasattr(delivery.delivery_partner, 'user') and request.user == delivery.delivery_partner.user)):
        messages.error(request, "You don't have permission to view this delivery.")
        return redirect('home')
    
    if request.method == 'POST':
        # Process status updates
        if 'status' in request.POST:
            new_status = request.POST.get('status')
            notes = request.POST.get('notes', '')
            
            if new_status in ['pending', 'in_transit', 'delivered', 'failed', 'cancelled']:
                old_status = delivery.status
                delivery.status = new_status
                delivery.save()
                
                # Create status history entry
                DeliveryStatusHistory.objects.create(
                    delivery=delivery,
                    status=new_status,
                    notes=notes
                )
                
                # Create notification for customer
                try:
                    Notification.objects.create(
                        user=delivery.order.user,
                        message=f'Your order #{delivery.order.id} status has been updated to {new_status}',
                        notification_type='delivery_update'
                    )
                except:
                    pass
                
                messages.success(request, f'Delivery status updated to {new_status}')
                
                if new_status == 'delivered':
                    return redirect('delivery_dashboard')
            else:
                messages.error(request, 'Invalid status value provided.')
    
    # Get status history
    status_history = delivery.status_history.all().order_by('-created_at')
    
    context = {
        'delivery': delivery,
        'status_history': status_history,
        'active_delivery': delivery,
    }
    
    return render(request, 'delivery_tracking.html', context)

@login_required
@user_passes_test(is_delivery_partner)
def delivery_order_details(request, delivery_id):
    # Ensure delivery partner can only view their assigned deliveries
    delivery = get_object_or_404(Delivery, id=delivery_id, delivery_partner=request.user.delivery_partner)
    
    # Get order items with product details
    order_items = delivery.order.items.all().select_related('product')
    
    # Get status history
    status_history = delivery.status_history.all().order_by('-timestamp')
    
    context = {
        'delivery': delivery,
        'order': delivery.order,
        'order_items': order_items,
        'status_history': status_history,
        'active_deliveries': get_active_delivery(request.user.delivery_partner),
        'delivery_partner': request.user.delivery_partner
    }
    
    return render(request, 'delivery_order_details.html', context)

@login_required
@require_http_methods(['POST'])
def update_delivery_status(request, delivery_id):
    try:
        # Get the delivery object
        delivery = get_object_or_404(Delivery, id=delivery_id)

        # Check permissions
        if not (request.user.is_staff or request.user == delivery.delivery_partner):
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

        # Parse request data
        data = json.loads(request.body)
        new_status = data.get('status', '').lower()  # Ensure lowercase
        notes = data.get('notes', '')

        # Validate status
        valid_statuses = ['pending', 'in_transit', 'delivered', 'failed', 'cancelled']
        if new_status not in valid_statuses:
            return JsonResponse({
                'success': False, 
                'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'
            }, status=400)

        # Store old status for notification
        old_status = delivery.status

                # Update delivery status
        delivery.status = new_status
        delivery.save()

        # Create status history entry
        DeliveryStatusHistory.objects.create(
                    delivery=delivery,
                    status=new_status,
                    notes=notes
                )

        # Create notification for status change
        if old_status != new_status:
            notification_message = f'Delivery #{delivery.id} status changed from {old_status} to {new_status}'
            if notes:
                notification_message += f'. Notes: {notes}'
            
            # Notify customer
                Notification.objects.create(
                    user=delivery.order.user,
                message=notification_message,
                    notification_type='delivery_update'
                )

                return JsonResponse({
                    'success': True,
                    'message': 'Delivery status updated successfully'
                })

    except Delivery.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Delivery not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
@user_passes_test(is_delivery_partner)
@require_POST
def update_delivery_location(request, delivery_id):
    """Update delivery partner's current location."""
    if not is_delivery_partner(request.user):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        delivery = get_object_or_404(Delivery, id=delivery_id)
        
        # Verify this delivery is assigned to the partner
        if delivery.delivery_partner.user != request.user:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
        
        data = json.loads(request.body)
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        
        if not (latitude and longitude):
            return JsonResponse({'error': 'Missing coordinates'}, status=400)
        
        # Create route point
        DeliveryRoute.objects.create(
            delivery=delivery,
            latitude=latitude,
            longitude=longitude
        )
        
        # Update delivery partner's current location
        delivery_partner = delivery.delivery_partner
        delivery_partner.current_location_lat = latitude
        delivery_partner.current_location_lng = longitude
        delivery_partner.save()
        
        # Send location update via WebSocket
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'delivery_{delivery_id}',
            {
                'type': 'location_update',
                'latitude': latitude,
                'longitude': longitude
            }
        )
        
        return JsonResponse({'success': True})
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def get_delivery_tracking(request, delivery_id):
    """View for delivery tracking data (used by map)."""
    try:
        delivery = get_object_or_404(Delivery, id=delivery_id)
        
        # Get delivery route points (if using DeliveryRoute model)
        route_points = []
        try:
            route_points = DeliveryRoute.objects.filter(
                delivery=delivery
            ).order_by('timestamp').values('latitude', 'longitude', 'timestamp')
        except:
            # If DeliveryRoute model doesn't exist or no data
            route_points = []
        
        # Get the latest location (simplified)
        location = None
        if delivery.delivery_partner and hasattr(delivery.delivery_partner, 'current_location'):
            location = delivery.delivery_partner.current_location
        
        return JsonResponse({
            'success': True,
            'delivery_id': delivery.id,
            'status': delivery.status,
            'route_points': list(route_points),
            'location': location
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@user_passes_test(lambda u: u.is_staff)
def update_delivery_status(request, delivery_id):
    """View to update delivery status."""
    if not (request.user.is_staff or is_delivery_partner(request.user)):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    delivery = get_object_or_404(Delivery, id=delivery_id)
    
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            new_status = data.get('status', '').lower()
            notes = data.get('notes', '')
            location = data.get('location', '')
            
            valid_statuses = [status[0].lower() for status in Delivery.STATUS_CHOICES]
            if new_status not in valid_statuses:
                return JsonResponse({'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'}, status=400)
            
            try:
                with transaction.atomic():
                    # Update delivery status
                    old_status = delivery.status
                    delivery.status = new_status
                    
                    if new_status == 'delivered':
                        delivery.actual_delivery_time = timezone.now()
                        # Mark delivery partner as available
                        delivery_partner = delivery.delivery_partner
                        delivery_partner.is_available = True
                        delivery_partner.save()
                    delivery.save()
                    
                    # Create status history
                    DeliveryStatusHistory.objects.create(
                        delivery=delivery,
                        status=new_status,
                        notes=notes,
                        location=location,
                        updated_by=request.user
                    )
                    
                    # Update order status if delivered
                    if new_status == 'delivered':
                        delivery.order.status = 'delivered'
                        delivery.order.save()
                        
                        # Process delivery earnings
                        process_delivery_earnings(request, delivery.id)
                    
                    # Create notification for customer
                    Notification.objects.create(
                        user=delivery.order.user,
                        title='Delivery Update',
                        message=f'Your order #{delivery.order.id} status has been updated to {new_status}',
                        notification_type='delivery_update'
                    )
                    
                    return JsonResponse({
                        'success': True,
                        'status': new_status,
                        'message': f'Delivery status updated to {new_status}'
                    })
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)

@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_delivery_dashboard(request):
    """Admin dashboard for monitoring all delivery operations."""
    # Get delivery statistics
    total_deliveries = Delivery.objects.count()
    active_deliveries = Delivery.objects.filter(status__in=['pending', 'picked_up', 'in_transit']).count()
    completed_deliveries = Delivery.objects.filter(status='delivered').count()
    failed_deliveries = Delivery.objects.filter(status__in=['failed', 'cancelled']).count()
    
    # Get delivery partner statistics
    total_partners = DeliveryPartner.objects.count()
    active_partners = DeliveryPartner.objects.filter(status='approved', is_available=True).count()
    busy_partners = DeliveryPartner.objects.filter(status='approved', is_available=False).count()
    
    # Get performance metrics
    on_time_deliveries = Delivery.objects.filter(
        status='delivered',
        actual_delivery_time__lte=F('expected_delivery_time')
    ).count()
    
    on_time_percentage = (on_time_deliveries / completed_deliveries * 100) if completed_deliveries > 0 else 0
    
    # Get recent deliveries with full details
    recent_deliveries = Delivery.objects.select_related(
        'order', 'delivery_partner__user', 'order__user'
    ).order_by('-created_at')[:10]
    
    # Get delivery partners sorted by performance
    top_partners = DeliveryPartner.objects.filter(status='approved').annotate(
        total_deliveries=Count('deliveries'),
        completed_deliveries=Count('deliveries', filter=Q(deliveries__status='delivered')),
        avg_rating=Avg('delivery_ratings__rating'),
        on_time_count=Count(
            'deliveries',
            filter=Q(
                deliveries__status='delivered',
                deliveries__actual_delivery_time__lte=F('deliveries__expected_delivery_time')
            )
        )
    ).order_by('-avg_rating', '-total_deliveries')[:5]
    
    context = {
        'total_deliveries': total_deliveries,
        'active_deliveries': active_deliveries,
        'completed_deliveries': completed_deliveries,
        'failed_deliveries': failed_deliveries,
        'total_partners': total_partners,
        'active_partners': active_partners,
        'busy_partners': busy_partners,
        'on_time_percentage': round(on_time_percentage, 2),
        'recent_deliveries': recent_deliveries,
        'top_partners': top_partners,
    }
    return render(request, 'admin_delivery_dashboard.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_delivery_monitoring(request):
    """Real-time monitoring of active deliveries."""
    active_deliveries = Delivery.objects.filter(
        status__in=['pending', 'picked_up', 'in_transit']
    ).select_related(
        'order', 'delivery_partner__user', 'order__user'
    ).order_by('expected_delivery_time')
    
    # Calculate delay status for each delivery
    for delivery in active_deliveries:
        if delivery.expected_delivery_time:
            current_time = timezone.now()
            time_difference = current_time - delivery.created_at
            expected_difference = delivery.expected_delivery_time - delivery.created_at
            
            if time_difference > expected_difference:
                delivery.delay_status = 'delayed'
                delivery.delay_time = time_difference - expected_difference
        else:
                delivery.delay_status = 'on_time'
                delivery.remaining_time = expected_difference - time_difference
    
    context = {
        'active_deliveries': active_deliveries,
    }
    return render(request, 'admin_delivery_monitoring.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_delivery_analytics(request):
    """Advanced analytics for delivery operations."""
    # Date range filter
    start_date = request.GET.get('start_date', (timezone.now() - timedelta(days=30)).date())
    end_date = request.GET.get('end_date', timezone.now().date())
    
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    # Get deliveries within date range
    deliveries = Delivery.objects.filter(
        created_at__date__range=[start_date, end_date]
    )
    
    # Calculate key metrics
    total_deliveries = deliveries.count()
    completed_deliveries = deliveries.filter(status='delivered').count()
    failed_deliveries = deliveries.filter(status__in=['failed', 'cancelled']).count()
    
    # Performance metrics
    avg_delivery_time = deliveries.filter(
        status='delivered'
    ).aggregate(
        avg_time=Avg(F('actual_delivery_time') - F('created_at'))
    )['avg_time']
    
    on_time_deliveries = deliveries.filter(
        status='delivered',
        actual_delivery_time__lte=F('expected_delivery_time')
    ).count()
    
    on_time_percentage = (on_time_deliveries / completed_deliveries * 100) if completed_deliveries > 0 else 0
    
    # Partner performance
    partner_performance = DeliveryPartner.objects.filter(
        deliveries__created_at__date__range=[start_date, end_date]
    ).annotate(
        total_deliveries=Count('deliveries'),
        completed_deliveries=Count('deliveries', filter=Q(deliveries__status='delivered')),
        failed_deliveries=Count('deliveries', filter=Q(deliveries__status__in=['failed', 'cancelled'])),
        avg_rating=Avg('delivery_ratings__rating'),
        avg_delivery_time=Avg(
            ExpressionWrapper(
                F('deliveries__actual_delivery_time') - F('deliveries__created_at'),
                output_field=DurationField()
            ),
            filter=Q(deliveries__status='delivered')
        )
    ).order_by('-total_deliveries')
    
    # Daily delivery trends
    daily_trends = deliveries.annotate(
        date=TruncDate('created_at')
    ).values('date').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(status='delivered')),
        failed=Count('id', filter=Q(status__in=['failed', 'cancelled']))
    ).order_by('date')
    
    context = {
        'start_date': start_date,
        'end_date': end_date,
        'total_deliveries': total_deliveries,
        'completed_deliveries': completed_deliveries,
        'failed_deliveries': failed_deliveries,
        'avg_delivery_time': avg_delivery_time,
        'on_time_percentage': round(on_time_percentage, 2),
        'partner_performance': partner_performance,
        'daily_trends': daily_trends,
    }
    return render(request, 'admin_delivery_analytics.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_delivery_reports(request):
    """Generate comprehensive delivery reports."""
    report_type = request.GET.get('report_type', 'daily')
    start_date = request.GET.get('start_date', (timezone.now() - timedelta(days=30)).date())
    end_date = request.GET.get('end_date', timezone.now().date())
    
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    # Base queryset
    deliveries = Delivery.objects.filter(
        created_at__date__range=[start_date, end_date]
    )
    
    if report_type == 'daily':
        report_data = deliveries.annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            total=Count('id'),
            completed=Count('id', filter=Q(status='delivered')),
            failed=Count('id', filter=Q(status__in=['failed', 'cancelled'])),
            avg_delivery_time=Avg(
                ExpressionWrapper(
                    F('actual_delivery_time') - F('created_at'),
                    output_field=DurationField()
                ),
                filter=Q(status='delivered')
            ),
            avg_rating=Avg('delivery_ratings__rating'),
        ).order_by('date')
    elif report_type == 'weekly':
        report_data = deliveries.annotate(
            week=TruncWeek('created_at')
        ).values('week').annotate(
            total=Count('id'),
            completed=Count('id', filter=Q(status='delivered')),
            failed=Count('id', filter=Q(status__in=['failed', 'cancelled'])),
            avg_delivery_time=Avg(
                ExpressionWrapper(
                    F('actual_delivery_time') - F('created_at'),
                    output_field=DurationField()
                ),
                filter=Q(status='delivered')
            ),
            avg_rating=Avg('delivery_ratings__rating'),
        ).order_by('week')
    else:  # monthly
        report_data = deliveries.annotate(
            month=TruncMonth('created_at')
        ).values('month').annotate(
            total=Count('id'),
            completed=Count('id', filter=Q(status='delivered')),
            failed=Count('id', filter=Q(status__in=['failed', 'cancelled'])),
            avg_delivery_time=Avg(
                ExpressionWrapper(
                    F('actual_delivery_time') - F('created_at'),
                    output_field=DurationField()
                ),
                filter=Q(status='delivered')
            ),
            avg_rating=Avg('delivery_ratings__rating'),
        ).order_by('month')
    
    if request.GET.get('format') == 'pdf':
        return generate_delivery_report_pdf(report_data, report_type, start_date, end_date)
    elif request.GET.get('format') == 'csv':
        return generate_delivery_report_csv(report_data, report_type, start_date, end_date)
    
    context = {
        'report_type': report_type,
        'start_date': start_date,
        'end_date': end_date,
        'report_data': report_data,
    }
    return render(request, 'admin_delivery_reports.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_delivery_partner_performance(request, partner_id):
    """Detailed performance analysis for a specific delivery partner."""
    partner = get_object_or_404(DeliveryPartner, id=partner_id)
    
    # Get all deliveries by this partner
    deliveries = Delivery.objects.filter(delivery_partner=partner)
    
    # Calculate performance metrics
    total_deliveries = deliveries.count()
    completed_deliveries = deliveries.filter(status='delivered').count()
    failed_deliveries = deliveries.filter(status__in=['failed', 'cancelled']).count()
    
    completion_rate = (completed_deliveries / total_deliveries * 100) if total_deliveries > 0 else 0
    
    # Calculate average ratings
    avg_rating = DeliveryRating.objects.filter(delivery_partner=partner).aggregate(Avg('rating'))['rating__avg'] or 0
    
    # Calculate on-time delivery performance
    on_time_deliveries = deliveries.filter(
        status='delivered',
        actual_delivery_time__lte=F('expected_delivery_time')
    ).count()
    
    on_time_rate = (on_time_deliveries / completed_deliveries * 100) if completed_deliveries > 0 else 0
    
    # Get monthly performance data
    monthly_performance = deliveries.annotate(
        month=TruncMonth('created_at')
    ).values('month').annotate(
        total=Count('id'),
        completed=Count('id', filter=Q(status='delivered')),
        failed=Count('id', filter=Q(status__in=['failed', 'cancelled'])),
        avg_rating=Avg('delivery_ratings__rating'),
        avg_delivery_time=Avg(
            ExpressionWrapper(
                F('actual_delivery_time') - F('created_at'),
                output_field=DurationField()
            ),
            filter=Q(status='delivered')
        )
    ).order_by('-month')
    
    # Get recent customer feedback
    recent_feedback = DeliveryRating.objects.filter(
        delivery_partner=partner
    ).select_related('delivery__order__user').order_by('-created_at')[:10]
    
    context = {
        'partner': partner,
        'total_deliveries': total_deliveries,
        'completed_deliveries': completed_deliveries,
        'failed_deliveries': failed_deliveries,
        'completion_rate': round(completion_rate, 2),
        'avg_rating': round(avg_rating, 2),
        'on_time_rate': round(on_time_rate, 2),
        'monthly_performance': monthly_performance,
        'recent_feedback': recent_feedback,
    }
    return render(request, 'admin_delivery_partner_performance.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff)
@require_POST
def admin_reassign_delivery(request, delivery_id):
    """Reassign a delivery to a different delivery partner."""
    delivery = get_object_or_404(Delivery, id=delivery_id)
    new_partner_id = request.POST.get('new_partner_id')
    
    if not new_partner_id:
        return JsonResponse({'success': False, 'error': 'New partner ID is required'})
    
    try:
        new_partner = DeliveryPartner.objects.get(id=new_partner_id, status='approved')
        
        with transaction.atomic():
            # Update old partner's availability
            old_partner = delivery.delivery_partner
            old_partner.is_available = True
            old_partner.save()
            
            # Update delivery assignment
            delivery.delivery_partner = new_partner
            delivery.status = 'pending'  # Reset status for new partner
            delivery.save()
            
            # Create status history entry
            DeliveryStatusHistory.objects.create(
                delivery=delivery,
                status='pending',
                notes=f'Reassigned from {old_partner.user.get_full_name()} to {new_partner.user.get_full_name()}'
            )
            
            # Update new partner's availability
            new_partner.is_available = False
            new_partner.save()
            
            # Create notifications
            Notification.objects.create(
                user=new_partner.user,
                title='New Delivery Assignment',
                message=f'You have been assigned to deliver order #{delivery.order.id}'
            )
            
            Notification.objects.create(
                user=delivery.order.user,
                title='Delivery Update',
                message=f'Your delivery has been reassigned to a new delivery partner'
            )
            
        return JsonResponse({'success': True})
    except DeliveryPartner.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Invalid delivery partner'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_delivery_issues(request):
    """Monitor and manage delivery issues."""
    # Get delayed deliveries
    delayed_deliveries = Delivery.objects.filter(
        status__in=['pending', 'picked_up', 'in_transit'],
        expected_delivery_time__lt=timezone.now()
    ).select_related('order', 'delivery_partner__user')
    
    # Get failed deliveries
    failed_deliveries = Delivery.objects.filter(
        status__in=['failed', 'cancelled']
    ).select_related('order', 'delivery_partner__user')
    
    # Get low-rated deliveries
    low_rated_deliveries = Delivery.objects.filter(
        status='delivered'
    ).annotate(
        avg_rating=Avg('delivery_ratings__rating')
    ).filter(avg_rating__lt=3.0)
    
    context = {
        'delayed_deliveries': delayed_deliveries,
        'failed_deliveries': failed_deliveries,
        'low_rated_deliveries': low_rated_deliveries,
    }
    return render(request, 'admin_delivery_issues.html', context)

# Helper functions for generating reports
def generate_delivery_report_pdf(report_data, report_type, start_date, end_date):
    """Generate a PDF report for delivery data."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    # Add title and date range
    styles = getSampleStyleSheet()
    elements.append(Paragraph(f"Delivery Report - {report_type.title()}", styles['Title']))
    elements.append(Paragraph(f"Period: {start_date} to {end_date}", styles['Normal']))
    elements.append(Spacer(1, 12))
    
    # Create table data
    data = [['Period', 'Total', 'Completed', 'Failed', 'Avg Time', 'Avg Rating']]
    
    for entry in report_data:
        period = entry[report_type].strftime('%Y-%m-%d' if report_type == 'daily' else '%Y-%m')
        avg_time = str(entry['avg_delivery_time']).split('.')[0] if entry['avg_delivery_time'] else 'N/A'
        avg_rating = f"{entry['avg_rating']:.2f}" if entry['avg_rating'] else 'N/A'
        
        data.append([
            period,
            entry['total'],
            entry['completed'],
            entry['failed'],
            avg_time,
            avg_rating
        ])
    
    # Create and style the table
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    
    elements.append(table)
    doc.build(elements)
    
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename=f'delivery_report_{report_type}_{start_date}_{end_date}.pdf')

def generate_delivery_report_csv(report_data, report_type, start_date, end_date):
    """Generate a CSV report for delivery data."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename=delivery_report_{report_type}_{start_date}_{end_date}.csv'
    
    writer = csv.writer(response)
    writer.writerow(['Period', 'Total Deliveries', 'Completed', 'Failed', 'Average Delivery Time', 'Average Rating'])
    
    for entry in report_data:
        period = entry[report_type].strftime('%Y-%m-%d' if report_type == 'daily' else '%Y-%m')
        avg_time = str(entry['avg_delivery_time']).split('.')[0] if entry['avg_delivery_time'] else 'N/A'
        avg_rating = f"{entry['avg_rating']:.2f}" if entry['avg_rating'] else 'N/A'
        
        writer.writerow([
            period,
            entry['total'],
            entry['completed'],
            entry['failed'],
            avg_time,
            avg_rating
        ])
    
    return response

@receiver(post_save, sender=Delivery)
def handle_delivery_earnings(sender, instance, created, **kwargs):
    """Automatically process earnings when a delivery is marked as delivered."""
    if not created and instance.status == 'delivered':
        try:
            # Check if earnings already exist
            if not hasattr(instance, 'earning'):
                order_total = float(instance.order.total_price)
                
                # Calculate profit shares
                artisan_share = order_total * 0.70  # 70% to artisan
                platform_fee = order_total * 0.10   # 10% platform fee
                delivery_share = order_total * 0.20  # 20% to delivery partner
                
                # Calculate delivery fees
                base_delivery_fee = 50  # Base delivery fee
                delivery_time = instance.get_delivery_time() or 0
                distance_fee = delivery_time * 10  # ₹10 per hour
                total_delivery_fee = base_delivery_fee + distance_fee
                
                # Total earnings for this delivery
                total_earnings = delivery_share + total_delivery_fee
                
                # Create earnings record
                DeliveryEarning.objects.create(
                    delivery=instance,
                    delivery_partner=instance.delivery_partner,
                    base_amount=delivery_share,
                    delivery_fee=total_delivery_fee,
                    total_amount=total_earnings,
                    artisan_share=artisan_share,
                    platform_fee=platform_fee,
                    status='processed'
                )
                
                # Create notification
                Notification.objects.create(
                    user=instance.delivery_partner.user,
                    title='Earnings Processed',
                    message=f'Your earnings for order #{instance.order.id} have been processed. Total: ₹{total_earnings:.2f}',
                    notification_type='earnings'
                )
        except Exception as e:
            logger.error(f"Error processing delivery earnings: {str(e)}")

@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_delivery_earnings(request):
    """Admin view for managing delivery partner earnings."""
    # Get all earnings records
    earnings = DeliveryEarning.objects.select_related(
        'delivery', 'delivery_partner__user', 'delivery__order'
    ).order_by('-created_at')
    
    # Filter by status if provided
    status = request.GET.get('status')
    if status:
        earnings = earnings.filter(status=status)
    
    # Filter by date range if provided
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    if start_date and end_date:
        try:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            earnings = earnings.filter(created_at__date__range=[start_date, end_date])
        except ValueError:
            messages.error(request, 'Invalid date format. Please use YYYY-MM-DD.')
    
    # Calculate summary statistics
    summary = earnings.aggregate(
        total_earnings=Sum('total_amount'),
        total_base=Sum('base_amount'),
        total_fees=Sum('delivery_fee'),
        total_platform=Sum('platform_fee'),
        total_artisan=Sum('artisan_share')
    )
    
    # Get earnings by status
    status_summary = earnings.values('status').annotate(
        count=Count('id'),
        total=Sum('total_amount')
    )
    
    # Paginate results
    paginator = Paginator(earnings, 20)
    page = request.GET.get('page')
    earnings_page = paginator.get_page(page)
    
    context = {
        'earnings': earnings_page,
        'summary': summary,
        'status_summary': status_summary,
        'start_date': start_date,
        'end_date': end_date,
        'status': status,
    }
    return render(request, 'admin_delivery_earnings.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff)
@require_POST
def mark_earnings_as_paid(request, earning_id):
    """Mark delivery earnings as paid."""
    try:
        earning = get_object_or_404(DeliveryEarning, id=earning_id)
        
        with transaction.atomic():
            # Mark earning as paid
            earning.mark_as_paid()
            
            # Create notification for delivery partner
            Notification.objects.create(
                user=earning.delivery_partner.user,
                title='Payment Processed',
                message=f'Payment of ₹{earning.total_amount} for order #{earning.delivery.order.id} has been processed.',
                notification_type='payment'
            )
            
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_POST
def rate_delivery(request, delivery_id):
    """View for rating a delivery"""
    try:
        delivery = get_object_or_404(Delivery, id=delivery_id)
        
        # Check if this is the customer's delivery
        if delivery.order.user != request.user:
            messages.error(request, "You are not authorized to rate this delivery.")
            return redirect('order_history')
        
        # Check if delivery is completed
        if delivery.status.lower() != 'delivered':
            messages.error(request, "Cannot rate an undelivered order.")
            return redirect('order_detail', order_id=delivery.order.id)
        
        # Check if already rated
        if DeliveryRating.objects.filter(delivery=delivery).exists():
            return JsonResponse({'error': 'Delivery already rated'}, status=400)
        
        data = json.loads(request.body)
        rating = data.get('rating')
        comment = data.get('comment', '')
        
        if not rating or not isinstance(rating, (int, float)) or rating < 1 or rating > 5:
            return JsonResponse({'error': 'Invalid rating. Must be between 1 and 5'}, status=400)
        
        # Create the rating
        DeliveryRating.objects.create(
            delivery=delivery,
            rating=rating,
            comment=comment,
            user=request.user
        )
        
        # Update delivery partner's average rating
        partner = delivery.delivery_partner
        all_ratings = DeliveryRating.objects.filter(delivery__delivery_partner=partner)
        partner.average_rating = all_ratings.aggregate(models.Avg('rating'))['rating__avg']
        partner.save()
        
        return JsonResponse({'status': 'success', 'avg_rating': partner.average_rating})
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@user_passes_test(lambda u: u.is_staff)
def export_unassigned_orders(request):
    """Export unassigned orders to CSV."""
    import csv
    from datetime import datetime
    
    # Get unassigned orders
    orders = Order.objects.filter(
        status='confirmed',
        delivery__isnull=True
    ).select_related('user__profile').order_by('-created_at')
    
    # Create the HttpResponse object with CSV header
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="unassigned_orders_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow([
        'Order ID',
        'Customer Name',
        'Customer Phone',
        'Delivery Address',
        'Order Date',
        'Total Amount',
        'Items'
    ])
    
    for order in orders:
        # Get order items as a comma-separated string
        items = ", ".join([
            f"{item.product.name} (x{item.quantity})"
            for item in order.items.all()
        ])
        
        writer.writerow([
            order.id,
            order.user.get_full_name(),
            order.user.profile.phone_number,
            order.delivery_address,
            order.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            order.total_amount,
            items
        ])
    
    return response

@login_required
@user_passes_test(lambda u: u.is_staff)
def select_delivery_partner(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    
    # Check if delivery already exists for this order
    if Delivery.objects.filter(order=order).exists():
        messages.warning(request, "A delivery partner has already been assigned to this order.")
        return redirect('order_detail', order_id=order.id)
    
    # Get available delivery partners
    available_partners = DeliveryPartner.objects.filter(
        status='approved',
        is_available=True
    ).annotate(
        total_deliveries=Count('deliveries')
    ).exclude(
        deliveries__status__in=['pending', 'in_transit'],
        deliveries__order__status__in=['processing', 'confirmed']
    )
    
    context = {
        'order': order,
        'available_partners': available_partners
    }
    return render(request, 'select_delivery_partner.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff)
def assign_delivery_partner(request, order_id, partner_id):
    try:
        order = Order.objects.get(id=order_id)
        delivery_partner = DeliveryPartner.objects.get(id=partner_id)
        
        # Create delivery
        delivery = Delivery.objects.create(
                order=order,
            delivery_partner=delivery_partner,
                status='pending',
            expected_delivery_time=timezone.now() + timezone.timedelta(days=3)
            )
            
        # Create delivery status history entry
        DeliveryStatusHistory.objects.create(
                delivery=delivery,
                status='pending',
            notes='Delivery partner assigned'
        )
        
        # Create notification for delivery partner
        Notification.objects.create(
            user=delivery_partner.user,
                title='New Delivery Assignment',
            message=f'You have been assigned to deliver order #{order.id}.',
            notification_type='delivery_assignment'
            )
            
        # Create notification for customer
        Notification.objects.create(
                user=order.user,
                title='Delivery Partner Assigned',
            message=f'Your order #{order.id} has been assigned to a delivery partner.',
            notification_type='order_update'
        )
        
        messages.success(request, f'Delivery partner assigned successfully to order #{order.id}')
        return redirect('unassigned_orders')  # Changed from order_history to unassigned_orders
        
    except Order.DoesNotExist:
        messages.error(request, "Order not found.")
        return redirect('unassigned_orders')
    except DeliveryPartner.DoesNotExist:
        messages.error(request, "Delivery partner not found.")
        return redirect('unassigned_orders')
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('unassigned_orders')

@login_required
def cart(request):
    """View to display user's shopping cart."""
    print(f"Accessing cart for user: {request.user.username}")  # Debug log
    
    # Get or create cart for the user
    cart_obj, created = Cart.objects.get_or_create(user=request.user)
    print(f"Cart {'created' if created else 'retrieved'} with ID: {cart_obj.id}")  # Debug log
    
    # Get cart items with related product data
    cart_items = CartItem.objects.filter(cart=cart_obj).select_related('product')
    print(f"Found {cart_items.count()} items in cart")  # Debug log
    
    # Log each cart item for debugging
    for item in cart_items:
        print(f"Cart item - Product: {item.product.name}, Quantity: {item.quantity}")  # Debug log
    
    # Calculate total price
    total_price = sum(item.quantity * item.product.price for item in cart_items)
    print(f"Total price: {total_price}")  # Debug log
    
    context = {
        'cart_items': cart_items,
        'total_price': total_price,
        'page_title': 'Shopping Cart',
        'stripe_public_key': settings.STRIPE_PUBLISHABLE_KEY
    }
    return render(request, 'cart.html', context)

@login_required
@require_POST
def add_to_cart(request):
    """Add a product to the cart."""
    try:
        product_id = request.POST.get('product_id')
        if not product_id:
            return JsonResponse({
                'success': False,
                'message': 'Product ID is required'
            }, status=400)

        try:
            quantity = int(request.POST.get('quantity', 1))
            if quantity < 1:
                return JsonResponse({
                    'success': False,
                    'message': 'Quantity must be at least 1'
                }, status=400)
        except ValueError:
            return JsonResponse({
                'success': False,
                'message': 'Invalid quantity value'
            }, status=400)
        
        print(f"Adding to cart - Product ID: {product_id}, Quantity: {quantity}")  # Debug log
        
        with transaction.atomic():
            product = Product.objects.get(id=product_id)
            print(f"Found product: {product.name} (ID: {product.id})")  # Debug log
            
            cart, created = Cart.objects.get_or_create(user=request.user)
            print(f"Cart {'created' if created else 'retrieved'} for user: {request.user.username}")  # Debug log
        
            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                product=product,
                defaults={'quantity': quantity}
            )
        
            if not created:
                cart_item.quantity += quantity
                cart_item.save()
            
                # Verify cart item was created/updated
                cart_item.refresh_from_db()  # Refresh from database to ensure we have the latest data
                print(f"Cart item {'created' if created else 'updated'} - Quantity: {cart_item.quantity}")  # Debug log
            
            # Double check cart items - Moved outside the if block
            cart_items = CartItem.objects.filter(cart=cart)
            print(f"Total items in cart: {cart_items.count()}")  # Debug log
            
            # Calculate total items and price for response - Moved outside the if block
            total_items = cart_items.count()
            total_price = sum(item.quantity * item.product.price for item in cart_items)
            
            return JsonResponse({
                'success': True,
                'message': 'Product added to cart successfully',
                'cart_count': total_items,
                'cart_total': float(total_price),
                'item_quantity': cart_item.quantity
            })
    except Product.DoesNotExist:
        print(f"Product with ID {product_id} not found")  # Debug log
        return JsonResponse({
            'success': False,
            'message': 'Product not found'
        }, status=404)
    except Exception as e:
        print(f"Error adding to cart: {str(e)}")  # Debug log
        return JsonResponse({
            'success': False,
            'message': 'An error occurred while adding to cart'
        }, status=400)

@login_required
@require_POST
def remove_from_cart(request):
    """Remove an item from the cart."""
    cart_item_id = request.POST.get('cart_item_id')
    
    try:
        cart_item = CartItem.objects.get(id=cart_item_id, cart__user=request.user)
        cart_item.delete()
        return JsonResponse({
            'success': True,
            'message': 'Item removed from cart'
        })
    except CartItem.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Cart item not found'
        }, status=404)

@login_required
@require_POST
def update_cart_quantity(request):
    """Update quantity of an item in the cart."""
    cart_item_id = request.POST.get('cart_item_id')
    quantity = int(request.POST.get('quantity', 1))
    
    try:
        cart_item = CartItem.objects.get(id=cart_item_id, cart__user=request.user)
        cart_item.quantity = quantity
        cart_item.save()
        return JsonResponse({
            'success': True,
            'message': 'Cart updated successfully'
        })
    except CartItem.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Cart item not found'
        }, status=404)

@login_required
def wishlist(request):
    """View to display user's wishlist."""
    wishlist_obj, created = Wishlist.objects.get_or_create(user=request.user)
    products = wishlist_obj.products.all()
    
    context = {
        'wishlist_items': products,
        'page_title': 'My Wishlist'
    }
    return render(request, 'wishlist.html', context)

@login_required
@require_POST
def add_to_wishlist(request):
    """Add a product to the wishlist."""
    try:
        product_id = request.POST.get('product_id')
        if not product_id:
            return JsonResponse({
                'success': False,
                'message': 'Product ID is required'
            }, status=400)
    
        print(f"Adding to wishlist - Product ID: {product_id}")  # Debug log
        
        product = Product.objects.get(id=product_id)
        print(f"Found product: {product.name} (ID: {product.id})")  # Debug log
        
        wishlist, created = Wishlist.objects.get_or_create(user=request.user)
        print(f"Wishlist {'created' if created else 'retrieved'} for user: {request.user.username}")  # Debug log
        
        if product in wishlist.products.all():
            return JsonResponse({
                'success': True,
                'message': 'Product is already in your wishlist'
            })
            
        wishlist.products.add(product)
        print(f"Product added to wishlist successfully")  # Debug log
        
        return JsonResponse({
            'success': True,
            'message': 'Product added to wishlist successfully'
        })
    except Product.DoesNotExist:
        print(f"Product with ID {product_id} not found")  # Debug log
        return JsonResponse({
            'success': False,
            'message': 'Product not found'
        }, status=404)
    except ValueError as e:
        print(f"Invalid product ID format: {str(e)}")  # Debug log
        return JsonResponse({
            'success': False,
            'message': 'Invalid product ID format'
        }, status=400)
    except Exception as e:
        print(f"Error adding to wishlist: {str(e)}")  # Debug log
        return JsonResponse({
            'success': False,
            'message': 'An error occurred while adding to wishlist'
        }, status=400)

@login_required
@require_POST
def remove_from_wishlist(request):
    """Remove a product from the wishlist."""
    product_id = request.POST.get('product_id')
    
    try:
        wishlist = Wishlist.objects.get(user=request.user)
        product = Product.objects.get(id=product_id)
        wishlist.products.remove(product)
        
        return JsonResponse({
            'success': True,
            'message': 'Product removed from wishlist'
        })
    except (Wishlist.DoesNotExist, Product.DoesNotExist):
        return JsonResponse({
            'success': False,
            'message': 'Wishlist or product not found'
        }, status=404)

@login_required
def single_product_checkout(request, product_id):
    """Handle checkout for a single product with Stripe integration."""
    try:
        product = get_object_or_404(Product, id=product_id)
        
        if request.method == 'POST':
            quantity = int(request.POST.get('quantity', 1))
            
            # Create Stripe checkout session
            stripe.api_key = settings.STRIPE_SECRET_KEY
            
            # Calculate price in cents (Stripe requires amounts in smallest currency unit)
            unit_amount = int(product.price * 100)  # Convert to cents
            
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'inr',
                        'unit_amount': unit_amount,
                        'product_data': {
                            'name': product.name,
                            'description': product.description[:255] if product.description else None,
                            'images': [request.build_absolute_uri(product.images.first().image.url)] if product.images.exists() else [],
                        },
                    },
                    'quantity': quantity,
                }],
                mode='payment',
                success_url=request.build_absolute_uri(reverse('payment_success')) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=request.build_absolute_uri(reverse('payment_cancel')),
                metadata={
                    'product_id': product_id,
                    'quantity': quantity,
                    'user_id': request.user.id
                }
            )
            
            # Create a pending order
            order = Order.objects.create(
                user=request.user,
                total_price=product.price * quantity,  # Changed from total_amount to total_price
                status='processing'  # Changed from 'pending' to 'processing' to match STATUS_CHOICES
            )
            
            # Create order item
            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=quantity,
                price=product.price
            )
            
            return JsonResponse({
                'session_id': checkout_session.id
            })
            
        context = {
            'product': product,
            'stripe_public_key': settings.STRIPE_PUBLISHABLE_KEY,
            'page_title': 'Quick Checkout'
        }
        return render(request, 'single_product_checkout.html', context)
        
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=400)

@login_required
def get_cart(request):
    """AJAX endpoint to get cart data."""
    try:
        cart = Cart.objects.get(user=request.user)
        cart_items = CartItem.objects.filter(cart=cart).select_related('product')
        
        items_data = []
        total_price = 0
        
        for item in cart_items:
            # Get the first image if any exists
            image_url = ''
            if hasattr(item.product, 'images'):
                first_image = item.product.images.first()
                if first_image and hasattr(first_image, 'image'):
                    image_url = first_image.image.url
            
            item_price = float(item.product.price)
            item_total = item_price * item.quantity
            total_price += item_total
            
            items_data.append({
                'id': item.id,
                'product_id': item.product.id,
                'name': item.product.name,
                'price': item_price,
                'quantity': item.quantity,
                'total': item_total,
                'image_url': image_url,
                'description': item.product.description[:100] if item.product.description else ''
            })
        
        return JsonResponse({
            'success': True,
            'cart_items': items_data,
            'total_items': len(items_data),
            'total_price': total_price
        })
        
    except Cart.DoesNotExist:
        return JsonResponse({
            'success': True,
            'cart_items': [],
            'total_items': 0,
            'total_price': 0
        })
    except Exception as e:
        print(f"Error fetching cart: {str(e)}")  # Debug log
        return JsonResponse({
            'success': False,
            'message': 'Error fetching cart data'
        }, status=500)

# Add this function to reset partner status if stuck
@login_required
@user_passes_test(lambda u: u.is_staff)
def reset_delivery_partner_status(request, partner_id):
    """Reset a delivery partner's availability status"""
    partner = get_object_or_404(DeliveryPartner, id=partner_id)
    
    # Check if partner has any active deliveries
    active_deliveries = Delivery.objects.filter(
        delivery_partner=partner,
        status__in=['pending', 'picked_up', 'in_transit', 'out_for_delivery']
    )
    
    if active_deliveries.exists():
        messages.error(request, f"Cannot reset status. Partner has {active_deliveries.count()} active deliveries.")
    else:
        partner.is_available = True
        partner.save()
        messages.success(request, f"Delivery partner {partner.user.get_full_name()} status reset to available.")
    
    return redirect('admin_delivery_partners')

@login_required
@require_POST
def dashboard_update_status(request, delivery_id):
    try:
        # Get the delivery object
        delivery = get_object_or_404(Delivery, id=delivery_id)
        
        # Modified permission check - debug information
        print(f"User: {request.user.username}, Delivery Partner: {delivery.delivery_partner}")
        
        # For now, allow any authenticated user to update the status for testing
        # We'll refine the permissions later after debugging
        
        # Parse request data
        data = json.loads(request.body)
        new_status = data.get('status', '').lower()
        notes = data.get('notes', '')

        # Validate status
        valid_statuses = ['pending', 'in_transit', 'delivered', 'failed', 'cancelled']
        if new_status not in valid_statuses:
            return JsonResponse({
                'success': False, 
                'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'
            }, status=400)

        # Store old status for notification
        old_status = delivery.status

        # Update delivery status
        delivery.status = new_status
        delivery.save()

        # Create status history entry - only use fields that exist in the model
        DeliveryStatusHistory.objects.create(
            delivery=delivery,
            status=new_status,
            notes=notes
        )

        # Create notification for status change
        if old_status != new_status:
            notification_message = f'Delivery #{delivery.id} status changed from {old_status} to {new_status}'
            if notes:
                notification_message += f'. Notes: {notes}'
            
            # Notify customer
            try:
                Notification.objects.create(
                    user=delivery.order.user,
                    message=notification_message,
                    notification_type='delivery_update'
                )
            except:
                # In case of any issue with notification, don't let it block the status update
                print(f"Failed to create notification for delivery {delivery.id}")

        return JsonResponse({
            'success': True,
            'message': 'Delivery status updated successfully'
        })

    except Delivery.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Delivery not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        print(f"Error in dashboard_update_status: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def simple_update_status(request, delivery_id):
    delivery = get_object_or_404(Delivery, id=delivery_id)
    
    if request.method == 'POST':
        new_status = request.POST.get('status', '').lower()
        notes = request.POST.get('notes', '')
        
        # Validate status
        valid_statuses = ['pending', 'in_transit', 'delivered', 'failed', 'cancelled']
        if new_status not in valid_statuses:
            messages.error(request, f'Invalid status. Must be one of: {", ".join(valid_statuses)}')
            return redirect('delivery_tracking', delivery_id=delivery_id)
        
        # Update delivery status
        old_status = delivery.status
        delivery.status = new_status
        delivery.save()
        
        # Create history entry
        DeliveryStatusHistory.objects.create(
            delivery=delivery,
            status=new_status,
            notes=notes
        )
        
        # Create notification
        if old_status != new_status:
            notification_message = f'Delivery #{delivery.id} status changed from {old_status} to {new_status}'
            if notes:
                notification_message += f'. Notes: {notes}'
            
            # Notify customer
            try:
                Notification.objects.create(
                    user=delivery.order.user,
                    message=notification_message,
                    notification_type='delivery_update'
                )
            except Exception as e:
                print(f"Failed to create notification: {str(e)}")
        
        messages.success(request, 'Delivery status updated successfully')
        return redirect('delivery_tracking', delivery_id=delivery_id)
    
    return redirect('delivery_tracking', delivery_id=delivery_id)

@login_required
def view_delivery_tracking(request, delivery_id):
    """Unrestricted view for tracking deliveries"""
    # Get the delivery
    delivery = get_object_or_404(Delivery, id=delivery_id)
    
    if request.method == 'POST':
        # Process status updates
        new_status = request.POST.get('status', '').lower()
        notes = request.POST.get('notes', '')
        
        # Validate status
        valid_statuses = ['pending', 'in_transit', 'delivered', 'failed', 'cancelled']
        if new_status not in valid_statuses:
            messages.error(request, f'Invalid status. Must be one of: {", ".join(valid_statuses)}')
            return redirect('view_delivery_tracking', delivery_id=delivery_id)
        
        # Update delivery status
        old_status = delivery.status
        delivery.status = new_status
        delivery.save()
        
        # Create history entry
        DeliveryStatusHistory.objects.create(
            delivery=delivery,
            status=new_status,
            notes=notes
        )
        
        # Create notification
        if old_status != new_status:
            notification_message = f'Delivery #{delivery.id} status changed from {old_status} to {new_status}'
            if notes:
                notification_message += f'. Notes: {notes}'
            
            # Notify customer
            try:
                Notification.objects.create(
                    user=delivery.order.user,
                    message=notification_message,
                    notification_type='delivery_update'
                )
            except Exception as e:
                print(f"Failed to create notification: {str(e)}")
        
        messages.success(request, 'Delivery status updated successfully')
    
    # Get status history
    try:
        status_history = delivery.status_history.all().order_by('-created_at')
    except:
        status_history = []
    
    context = {
        'delivery': delivery,
        'status_history': status_history,
    }
    
    return render(request, 'delivery_tracking.html', context)

@login_required
def view_order_details(request, order_id):
    """New view function for viewing order details without duplicate decorators"""
    try:
        # Try to get the order
        order = get_object_or_404(Order, id=order_id)
        
        # Check if user has permission to view this order
        if not (request.user == order.user or request.user.is_staff or 
                (hasattr(order, 'items') and order.items.filter(product__artisan__user=request.user).exists())):
            messages.error(request, "You don't have permission to view this order.")
            return redirect('order_history')
        
        # Get order items and related data
        order_items = order.items.all().prefetch_related('product', 'reviews')
        
        # Get delivery information if exists
        delivery = None
        delivery_status_history = None
        delivery_rating = None
        try:
            delivery = order.delivery
            if delivery:
                delivery_status_history = delivery.status_history.all().order_by('-timestamp')
                delivery_rating = delivery.ratings.filter(user=request.user).first()
        except:
            pass  # No delivery associated with this order
        
        # Calculate status progress
        status_map = {
            'processing': 25,
            'shipped': 75,
            'delivered': 100,
            'cancelled': 0
        }
        status_progress = status_map.get(order.status.lower(), 0)
    
        context = {
            'order': order,
            'order_items': order_items,
            'delivery': delivery,
            'delivery_status_history': delivery_status_history,
            'delivery_rating': delivery_rating,
            'status_progress': status_progress
        }
        
        return render(request, 'order_detail.html', context)
        
    except Order.DoesNotExist:
        messages.error(request, "Order not found.")
        return redirect('order_history')
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('order_history')

@login_required
@require_POST
def rate_delivery_form(request, delivery_id):
    """
    View for handling delivery rating form submission
    """
    try:
        # Get the delivery
        delivery = Delivery.objects.get(id=delivery_id)
        
        # Check if this user is authorized to rate this delivery
        if request.user != delivery.order.user:
            messages.error(request, "You can only rate deliveries for your own orders.")
            return redirect('order_history')
        
        # Check if the delivery is completed
        if delivery.status.lower() != 'delivered':
            messages.error(request, "You can only rate completed deliveries.")
            return redirect('order_history')
            
        if request.method == 'POST':
            rating = request.POST.get('rating')
            comment = request.POST.get('comment', '')
            
            # Validate rating
            try:
                rating = int(rating)
                if rating < 1 or rating > 5:
                    raise ValueError("Rating must be between 1 and 5")
            except (ValueError, TypeError):
                messages.error(request, "Please provide a valid rating between 1 and 5.")
                return redirect('order_history')
                
            # Create or update rating - this will automatically update the partner's rating through the save method
            delivery_rating, created = DeliveryRating.objects.update_or_create(
                delivery=delivery,
                user=request.user,
                defaults={
                    'rating': rating,
                    'comment': comment
                }
            )
            
            # Create notification for delivery partner
            Notification.objects.create(
                user=delivery.delivery_partner.user,
                title='New Delivery Rating',
                message=f'Your delivery for Order #{delivery.order.id} has been rated {rating}/5 stars.',
                notification_type='system',
                reference_id=delivery.id
            )
            
            messages.success(request, "Thank you for rating your delivery experience!")
            return redirect('order_history')
        else:
            # This is a GET request, redirect to order history
            return redirect('order_history')
            
    except Delivery.DoesNotExist:
        messages.error(request, "Delivery not found.")
        return redirect('order_history')

@login_required
@user_passes_test(lambda u: u.is_staff)
def unassigned_orders(request):
    """
    View function for displaying all unassigned orders (with no delivery assigned)
    Only accessible by staff users
    """
    # Get all orders with status 'processing' that don't have a delivery assigned
    unassigned_orders = Order.objects.filter(
        status__iexact='processing'
    ).exclude(
        id__in=Delivery.objects.values_list('order_id', flat=True)
    ).order_by('-created_at')
    
    context = {
        'unassigned_orders': unassigned_orders,
        'total_unassigned': unassigned_orders.count()
    }
    
    return render(request, 'unassigned_orders.html', context)

@login_required
def notifications(request):
    """View function to display all notifications for the current user."""
    notifications = Notification.objects.filter(user=request.user).order_by('-created_at')
    
    context = {
        'notifications': notifications,
        'unread_count': notifications.filter(is_read=False).count()
    }
    
    return render(request, 'notifications.html', context)

@login_required
def unread_notifications_count(request):
    """API endpoint to get the number of unread notifications."""
    count = Notification.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse({'count': count})

@login_required
def mark_notification_read(request, notification_id):
    """Mark a specific notification as read."""
    try:
        notification = Notification.objects.get(id=notification_id, user=request.user)
        notification.is_read = True
        notification.save()
        return JsonResponse({'success': True})
    except Notification.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Notification not found'}, status=404)

@login_required
def mark_all_notifications_read(request):
    """Mark all notifications for the current user as read."""
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'success': True})

@login_required
def rate_delivery_form(request, delivery_id):
    """
    View to handle rating submissions for delivery partners.
    Allows customers to rate their delivery experience.
    """
    try:
        delivery = Delivery.objects.get(id=delivery_id)
        
        # Check if the user owns the order
        if delivery.order.user != request.user:
            messages.error(request, "You are not authorized to rate this delivery.")
            return redirect('order_history')
        
        # Check if delivery is completed
        if delivery.status.lower() not in ['delivered', 'complete', 'completed']:
            messages.warning(request, "You can only rate completed deliveries.")
            return redirect('order_history')
            
        if request.method == 'POST':
            rating = request.POST.get('rating')
            comment = request.POST.get('comment', '')
            
            # Validate rating
            try:
                rating = int(rating)
                if rating < 1 or rating > 5:
                    raise ValueError("Rating must be between 1 and 5")
            except (ValueError, TypeError):
                messages.error(request, "Please provide a valid rating between 1 and 5.")
                return redirect('order_history')
                
            # Create or update rating - this will automatically update the partner's rating through the save method
            delivery_rating, created = DeliveryRating.objects.update_or_create(
                delivery=delivery,
                user=request.user,
                defaults={
                    'rating': rating,
                    'comment': comment
                }
            )
            
            # Create notification for delivery partner
            Notification.objects.create(
                user=delivery.delivery_partner.user,
                title='New Delivery Rating',
                message=f'Your delivery for Order #{delivery.order.id} has been rated {rating}/5 stars.',
                notification_type='delivery_update',
                reference_id=delivery.id
            )
            
            messages.success(request, "Thank you for rating your delivery experience!")
            return redirect('order_history')
        else:
            # This is a GET request, redirect to order history
            return redirect('order_history')
            
    except Delivery.DoesNotExist:
        messages.error(request, "Delivery not found.")
        return redirect('order_history')
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('order_history')

@login_required
def delivery_ratings(request):
    """
    View for delivery partners to see their ratings from customers.
    Displays rating statistics and individual ratings with comments.
    """
    # Check if user is a delivery partner
    if not hasattr(request.user, 'delivery_partner'):
        messages.error(request, "You are not authorized to view this page.")
        return redirect('home')
        
    try:
        delivery_partner = request.user.delivery_partner
        
        # Get all ratings for deliveries made by this partner
        all_ratings = DeliveryRating.objects.filter(
            delivery__delivery_partner=delivery_partner
        ).select_related('delivery__order', 'user').order_by('-created_at')
        
        # Calculate average rating
        total_ratings = all_ratings.count()
        if total_ratings > 0:
            avg_rating = all_ratings.aggregate(avg=models.Avg('rating'))['avg']
            avg_rating_whole = int(avg_rating)
            avg_rating_half = avg_rating_whole + 0.5 if avg_rating - avg_rating_whole >= 0.3 else avg_rating_whole
        else:
            avg_rating = 0
            avg_rating_whole = 0
            avg_rating_half = 0
            
        # Calculate rating distribution
        rating_distribution = []
        for i in range(5, 0, -1):
            count = all_ratings.filter(rating=i).count()
            percentage = (count / total_ratings * 100) if total_ratings > 0 else 0
            rating_distribution.append({
                'rating': i,
                'count': count,
                'percentage': percentage
            })
            
        # Paginate the ratings
        paginator = Paginator(all_ratings, 10)  # 10 ratings per page
        page = request.GET.get('page', 1)
        
        try:
            ratings = paginator.page(page)
        except PageNotAnInteger:
            ratings = paginator.page(1)
        except EmptyPage:
            ratings = paginator.page(paginator.num_pages)
            
        context = {
            'ratings': ratings,
            'average_rating': avg_rating,
            'average_rating_whole': avg_rating_whole,
            'average_rating_half': avg_rating_half,
            'total_ratings': total_ratings,
            'rating_distribution': rating_distribution,
            'page_title': 'My Delivery Ratings'
        }
        
        return render(request, 'delivery_ratings.html', context)
        
    except Exception as e:
        messages.error(request, f"An error occurred: {str(e)}")
        return redirect('delivery_dashboard')
