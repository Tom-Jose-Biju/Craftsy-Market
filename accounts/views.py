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
from django.db.models import Q, Sum, Avg, Count, F, FloatField, ExpressionWrapper, Case, When, DurationField, DecimalField
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
    return user.is_authenticated and user.user_type == 'delivery_partner'

def get_active_delivery(delivery_partner):
    return Delivery.objects.filter(
        delivery_partner=delivery_partner,
        status__in=['pending', 'in_transit']
    ).first()

@lru_cache(maxsize=1)
def get_image_classifier():
    processor = ViTImageProcessor.from_pretrained('google/vit-base-patch16-224')
    model = ViTForImageClassification.from_pretrained('google/vit-base-patch16-224')
    return processor, model

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
        else:
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'login.html', {
        'next': request.GET.get('next', '')
    })

@login_required
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
    unread_notifications_count = request.user.notifications.filter(is_read=False).count()
    recent_notifications = request.user.notifications.all()[:5]  # Get 5 most recent notifications

    context = {
        'total_users': User.objects.count(),
        'total_artisans': User.objects.filter(user_type='artisan').count(),
        'total_products': Product.objects.count(),
        'total_delivery_partners': DeliveryPartner.objects.count(),
        'pending_partners': DeliveryPartner.objects.filter(status='pending').count(),
        'unassigned_orders': Order.objects.filter(status='confirmed', delivery__isnull=True).count(),
        'recent_products': Product.objects.all().order_by('-created_at')[:5],
        # Add notification data to context
        'unread_notifications_count': unread_notifications_count,
        'recent_notifications': recent_notifications,
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
        else:
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
@require_http_methods(["POST", "GET"])  # Allow both POST and GET
@login_required
def checkout(request):
    if request.method == 'POST':
        try:
            cart_data = json.loads(request.body)
            line_items = []

            for item in cart_data:
                product = Product.objects.get(id=item['id'])
                line_items.append({
                    'price_data': {
                        'currency': 'inr',
                        'unit_amount': int(product.price * 100),
                        'product_data': {
                            'name': product.name,
                            'description': product.description[:100],
                        },
                    },
                    'quantity': item['quantity'],
                })

            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=line_items,
                mode='payment',
                success_url=request.build_absolute_uri(reverse('payment_success')),
                cancel_url=request.build_absolute_uri(reverse('payment_cancel')),
            )
            return JsonResponse({'success': True, 'checkout_url': checkout_session.url})
        except Product.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'One or more products in your cart are no longer available.'}, status=400)
        except stripe.error.StripeError as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'error': 'An unexpected error occurred. Please try again.'}, status=500)
    else:
        # Handle GET request, e.g., render a checkout page
        context = {
            'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY  # Ensure this is set
        }
        return render(request, 'checkout.html', context)


@require_GET
def payment_success(request):
    return render(request, 'payment_success.html')

@require_GET
def payment_cancel(request):
    return render(request, 'payment_cancel.html')

# New views for cart and wishlist
@login_required
def cart(request):
    if request.user.is_authenticated:
        cart, created = Cart.objects.get_or_create(user=request.user)
        cart_items = cart.items.all()
    else:
        session_cart = request.session.get('cart', {})
        cart_items = []
        for product_id, quantity in session_cart.items():
            product = get_object_or_404(Product, id=product_id)
            cart_items.append({
                'product': product,
                'quantity': quantity,
                'item_total': product.price * quantity
            })

    total = sum(item.product.price * item.quantity for item in cart_items)
    
    context = {
        'cart_items': cart_items,
        'total': total,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY
    }
    return render(request, 'cart.html', context)

@login_required
def wishlist(request):
    wishlist = request.session.get('wishlist', [])
    wishlist_items = Product.objects.filter(id__in=wishlist)

    gst_rate = Decimal(str(settings.GST_RATE))
    
    for item in wishlist_items:
        item.gst_amount = item.price * gst_rate
        item.total_price = item.price + item.gst_amount

    context = {
        'wishlist_items': wishlist_items,
        'GST_RATE': gst_rate * 100,
    }
    return render(request, 'wishlist.html', context)

@login_required
@require_POST
def single_product_checkout(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    quantity = int(request.POST.get('quantity', 1))  # Get quantity from POST data

    gst_rate = Decimal(str(settings.GST_RATE))
    base_price = product.price
    gst_amount = base_price * gst_rate
    total_price = base_price + gst_amount

    line_items = [{
        'price_data': {
            'currency': 'inr',
            'unit_amount': int(total_price * 100),  # Stripe expects amount in cents
            'product_data': {
                'name': product.name,
                'description': f'Base Price: ₹{base_price}, GST: ₹{gst_amount}',
            },
        },
        'quantity': quantity,
    }]

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url=request.build_absolute_uri(reverse('payment_success')) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.build_absolute_uri(reverse('payment_cancel')),
        )
        return JsonResponse({'success': True, 'checkout_url': checkout_session.url})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
@require_POST
def add_to_cart(request):
    try:
        product_id = request.POST.get('product_id')
        quantity = int(request.POST.get('quantity', 1))
        
        if not product_id:
            return JsonResponse({'success': False, 'error': 'Product ID is required'})
        
        product = get_object_or_404(Product, id=product_id)
        
        if product.inventory < quantity:
            return JsonResponse({'success': False, 'error': 'Not enough inventory'})
        
        if request.user.is_authenticated:
            cart, created = Cart.objects.get_or_create(user=request.user)
            cart_item, item_created = CartItem.objects.get_or_create(cart=cart, product=product)
            
            if item_created:
                cart_item.quantity = quantity
            else:
                cart_item.quantity += quantity
            
            cart_item.save()
        else:
            cart = request.session.get('cart', {})
            cart[product_id] = cart.get(product_id, 0) + quantity
            request.session['cart'] = cart
        
        # Update the product inventory
        product.inventory -= quantity
        product.save()
        
        return JsonResponse({
            'success': True,
            'new_inventory': product.inventory
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@require_POST
def remove_from_cart(request):
    product_id = request.POST.get('product_id')
    
    if request.user.is_authenticated:
        cart = Cart.objects.get(user=request.user)
        try:
            cart_item = CartItem.objects.get(cart=cart, product_id=product_id)
            product = cart_item.product
            product.inventory += cart_item.quantity
            product.save()
            cart_item.delete()
        except CartItem.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Product not in cart'})
    else:
        cart = request.session.get('cart', {})
        if str(product_id) in cart:
            product = get_object_or_404(Product, id=product_id)
            product.inventory += cart[str(product_id)]
            product.save()
            del cart[str(product_id)]
            request.session['cart'] = cart
    
    return JsonResponse({'success': True, 'new_inventory': product.inventory})

@require_POST
def update_cart_quantity(request):
    product_id = request.POST.get('product_id')
    new_quantity = int(request.POST.get('quantity', 1))
    
    product = get_object_or_404(Product, id=product_id)
    
    if request.user.is_authenticated:
        cart, created = Cart.objects.get_or_create(user=request.user)
        try:
            cart_item = CartItem.objects.get(cart=cart, product=product)
            quantity_difference = new_quantity - cart_item.quantity
            
            if product.inventory < quantity_difference:
                return JsonResponse({'success': False, 'error': 'Not enough inventory'})
            
            if new_quantity > 0:
                cart_item.quantity = new_quantity
                cart_item.save()
            else:
                cart_item.delete()
            
            product.inventory -= quantity_difference
            product.save()
        except CartItem.DoesNotExist:
            if new_quantity > 0:
                if product.inventory < new_quantity:
                    return JsonResponse({'success': False, 'error': 'Not enough inventory'})
                CartItem.objects.create(cart=cart, product=product, quantity=new_quantity)
                product.inventory -= new_quantity
                product.save()
            else:
                return JsonResponse({'success': False, 'error': 'Product not in cart'})
    else:
        cart = request.session.get('cart', {})
        if str(product_id) in cart:
            quantity_difference = new_quantity - cart[str(product_id)]
            if product.inventory < quantity_difference:
                return JsonResponse({'success': False, 'error': 'Not enough inventory'})
            
            if new_quantity > 0:
                cart[str(product_id)] = new_quantity
            else:
                del cart[str(product_id)]
            
            request.session['cart'] = cart
            product.inventory -= quantity_difference
            product.save()
        else:
            if new_quantity > 0:
                if product.inventory < new_quantity:
                    return JsonResponse({'success': False, 'error': 'Not enough inventory'})
                cart[str(product_id)] = new_quantity
                request.session['cart'] = cart
                product.inventory -= new_quantity
                product.save()
            else:
                return JsonResponse({'success': False, 'error': 'Product not in cart'})
    
    return JsonResponse({'success': True, 'new_inventory': product.inventory})


@login_required
def get_cart(request):
    cart = Cart.objects.get(user=request.user)
    cart_items = cart.items.all()
    total_items = sum(item.quantity for item in cart_items)
    
    gst_rate = Decimal(str(settings.GST_RATE))
    
    cart_data = []
    total = Decimal('0.00')
    total_gst = Decimal('0.00')
    
    for item in cart_items:
        base_price = item.product.price * item.quantity
        gst_amount = base_price * gst_rate
        item_total = base_price + gst_amount
        
        total += item_total
        total_gst += gst_amount
        
        cart_data.append({
            'id': item.product.id,
            'name': item.product.name,
            'quantity': item.quantity,
            'base_price': float(base_price),
            'gst_amount': float(gst_amount),
            'total_price': float(item_total),
            'image_url': item.product.images.first().image.url if item.product.images.exists() else '',
        })
    
    return JsonResponse({
        'cart_items': cart_data,
        'total_items': total_items,
        'subtotal': float(total - total_gst),
        'total_gst': float(total_gst),
        'total': float(total),
    })


@login_required
@require_POST
def add_to_wishlist(request):
    product_id = request.POST.get('product_id')
    
    wishlist = request.session.get('wishlist', [])
    
    if product_id not in wishlist:
        wishlist.append(product_id)
        request.session['wishlist'] = wishlist
        request.session.modified = True
        return JsonResponse({'success': True})
    else:
        return JsonResponse({'success': False, 'error': 'Product already in wishlist'})

@login_required
@require_POST
def remove_from_wishlist(request):
    product_id = request.POST.get('product_id')
    
    wishlist = request.session.get('wishlist', [])
    
    if product_id in wishlist:
        wishlist.remove(product_id)
        request.session['wishlist'] = wishlist
        request.session.modified = True
        return JsonResponse({'success': True})
    else:
        return JsonResponse({'success': False, 'error': 'Product not in wishlist'})

@login_required
@require_POST
def create_checkout_session(request):
    try:
        cart, created = Cart.objects.get_or_create(user=request.user)
        cart_items = CartItem.objects.filter(cart=cart)
        
        if not cart_items:
            return JsonResponse({'success': False, 'error': 'Cart is empty'})

        line_items = []
        for cart_item in cart_items:
            line_items.append({
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': int(cart_item.product.price * 100),
                    'product_data': {
                        'name': cart_item.product.name,
                    },
                },
                'quantity': cart_item.quantity,
            })

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url=request.build_absolute_uri(reverse('payment_success')),
            cancel_url=request.build_absolute_uri(reverse('payment_cancel')),
        )
        return JsonResponse({'success': True, 'session_id': checkout_session.id})
    except stripe.error.StripeError as e:
        return JsonResponse({'success': False, 'error': str(e)})
    except Exception as e:
        return JsonResponse({'success': False, 'error': 'An unexpected error occurred'})

@login_required
def payment_success(request):
    try:
        cart, created = Cart.objects.get_or_create(user=request.user)
        cart_items = CartItem.objects.filter(cart=cart)
        
        if not cart_items:
            messages.warning(request, "Your cart is empty.")
            return redirect('home')

        total_price = sum(item.product.price * item.quantity for item in cart_items)

        # Create the order with auto-now fields
        order = Order.objects.create(
            user=request.user,
            total_price=total_price,
            status='processing'
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
            message=f'Your order #{order.id} has been placed successfully. Please select a delivery partner.',
            notification_type='order_update'
        )

        # Redirect to delivery partner selection
        return redirect('select_delivery_partner', order_id=order.id)
        
    except Exception as e:
        messages.error(request, f"An error occurred while processing your order: {str(e)}")
        return redirect('cart')

@login_required
def select_delivery_partner(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    
    # Check if delivery already exists for this order
    if Delivery.objects.filter(order=order).exists():
        messages.warning(request, "A delivery partner has already been assigned to this order.")
        return redirect('order_detail', order_id=order.id)
    
    # Get available delivery partners
    available_partners = DeliveryPartner.objects.filter(
        status='approved',
        is_available=True
    ).annotate(
        total_deliveries=Count('deliveries'),
        average_rating=Avg('delivery_ratings__rating')
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
def assign_delivery_partner(request, order_id, partner_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    order = get_object_or_404(Order, id=order_id, user=request.user)
    partner = get_object_or_404(DeliveryPartner, id=partner_id, status='approved', is_available=True)
    
    # Check if delivery already exists
    if Delivery.objects.filter(order=order).exists():
        messages.error(request, "This order already has a delivery partner assigned.")
        return redirect('order_detail', order_id=order.id)
    
    try:
        with transaction.atomic():
            # Get user's profile for address
            user_profile = request.user.profile
            
            # Create delivery record with address
            delivery = Delivery.objects.create(
                order=order,
                delivery_partner=partner,
                status='pending',
                delivery_address=f"{user_profile.street_address}, {user_profile.city}, {user_profile.state}, {user_profile.postal_code}",
                expected_delivery_time=timezone.now() + timedelta(days=3)
            )
            
            # Create initial status history
            DeliveryStatusHistory.objects.create(
                delivery=delivery,
                status='pending',
                notes='Delivery assigned by customer'
            )
            
            # Update order status
            order.status = 'confirmed'
            order.save()
            
            # Update delivery partner availability
            partner.is_available = False
            partner.save()
            
            # Create notifications
            Notification.objects.create(
                user=partner.user,
                title='New Delivery Assignment',
                message=f'You have been assigned to deliver order #{order.id}',
                notification_type='delivery_assignment'
            )
            
            Notification.objects.create(
                user=order.user,
                title='Delivery Partner Assigned',
                message=f'Your order #{order.id} has been assigned to {partner.user.get_full_name()}',
                notification_type='order_update'
            )
            
            messages.success(request, 'Delivery partner assigned successfully!')
            return redirect('order_detail', order_id=order.id)
            
    except Exception as e:
        messages.error(request, f'Error assigning delivery partner: {str(e)}')
        return redirect('select_delivery_partner', order_id=order.id)

@login_required
def payment_cancel(request):
    messages.warning(request, "Payment cancelled. Your cart items are still saved.")
    return redirect('cart')


@login_required
def order_history(request):
    orders = Order.objects.filter(user=request.user).order_by('-created_at')
    processing_orders = orders.filter(status='processing')
    shipped_orders = orders.filter(status='shipped')
    delivered_orders = orders.filter(status='delivered')

    context = {
        'orders': orders,
        'processing_orders': processing_orders,
        'shipped_orders': shipped_orders,
        'delivered_orders': delivered_orders,
    }
    return render(request, 'order_history.html', context)

@login_required
@login_required
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    profile = Profile.objects.get(user=request.user)
    
    # Get delivery information if it exists
    try:
        delivery = order.delivery
        delivery_status_history = delivery.status_history.all()
    except Delivery.DoesNotExist:
        delivery = None
        delivery_status_history = None
    
    # Calculate the status progress
    status_progress = {
        'processing': 25,
        'shipped': 75,
        'delivered': 100
    }.get(order.status.lower(), 0)
    
    # Fetch all reviews for each product in the order
    order_items = order.items.all().select_related('product')
    for item in order_items:
        item.reviews = Review.objects.filter(product=item.product, user=request.user).order_by('-created_at')
    
    context = {
        'order': order,
        'order_items': order_items,
        'profile': profile,
        'status_progress': status_progress,
        'user': request.user,
        'delivery': delivery,
        'delivery_status_history': delivery_status_history,
    }
    return render(request, 'order_detail.html', context)

@login_required
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
def artisan_earnings(request):
    artisan = request.user.artisan
    completed_orders = Order.objects.filter(items__product__artisan=artisan, status='delivered').distinct()
    
    total_earnings = completed_orders.aggregate(Sum('total_price'))['total_price__sum'] or 0
    monthly_earnings = completed_orders.filter(created_at__gte=timezone.now() - timezone.timedelta(days=30)).aggregate(Sum('total_price'))['total_price__sum'] or 0
    average_order_value = total_earnings / completed_orders.count() if completed_orders.count() > 0 else 0
    
    # Monthly earnings data for chart
    monthly_earnings_data = list(completed_orders.annotate(month=TruncMonth('created_at')).values('month').annotate(earnings=Sum('total_price')).order_by('month'))
    monthly_earnings_labels = [entry['month'].strftime("%B %Y") for entry in monthly_earnings_data]
    monthly_earnings_values = [float(entry['earnings']) for entry in monthly_earnings_data]
    
    # Top selling products data for chart
    top_products = Product.objects.filter(artisan=artisan).annotate(sales_count=Count('orderitem')).order_by('-sales_count')[:5]
    top_products_labels = [product.name for product in top_products]
    top_products_data = [product.sales_count for product in top_products]
    
    # Recent transactions
    recent_transactions = OrderItem.objects.filter(product__artisan=artisan, order__status='delivered').order_by('-order__created_at')[:10]
    
    context = {
        'total_earnings': total_earnings,
        'monthly_earnings': monthly_earnings,
        'average_order_value': average_order_value,
        'completed_orders': completed_orders.count(),
        'monthly_earnings_labels': json.dumps(monthly_earnings_labels),
        'monthly_earnings_data': monthly_earnings_values,
        'top_products_labels': json.dumps(top_products_labels),
        'top_products_data': top_products_data,
        'recent_transactions': recent_transactions,
    }
    
    return render(request, 'artisan_earnings.html', context)

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
        ('BACKGROUND', (0, 0), (-1, -1), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
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
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
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
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
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
                delivery_partner.current_delivery = None
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
    
    return redirect('order_detail', order_id=order_id)

@login_required
@user_passes_test(lambda u: u.is_staff)
def admin_delivery_partners(request):
    if request.method == 'POST':
        partner_id = request.POST.get('partner_id')
        action = request.POST.get('action')
        
        if partner_id and action in ['approve', 'reject']:
            partner = get_object_or_404(DeliveryPartner, id=partner_id)
            
            if action == 'approve':
                partner.status = 'approved'
                partner.is_available = True
                messages.success(request, f'Delivery partner {partner.user.get_full_name()} has been approved.')
            else:  # reject
                partner.status = 'rejected'
                partner.is_available = False
                messages.warning(request, f'Delivery partner {partner.user.get_full_name()} has been rejected.')
            
            partner.save()
            
            # Send email notification to the delivery partner
            subject = 'Craftsy Delivery Partner Application Update'
            if action == 'approve':
                message = 'Congratulations! Your application to become a delivery partner has been approved.'
            else:
                message = 'We regret to inform you that your application to become a delivery partner has been rejected.'
            
            try:
                send_mail(
                    subject,
                    message,
                    'noreply@craftsy.com',
                    [partner.user.email],
                    fail_silently=True
                )
            except Exception as e:
                messages.warning(request, f'Email notification could not be sent: {str(e)}')
            
            return redirect('admin_delivery_partners')
    
    # Get all delivery partners
    all_partners = DeliveryPartner.objects.all()
    
    # Get pending partners
    pending_partners = all_partners.filter(status='pending')
    
    # Get active partners with their statistics
    active_partners = all_partners.filter(status='approved').annotate(
        total_deliveries=Count('deliveries'),
        rating=Avg('delivery_ratings__rating')
    )
    
    context = {
        'total_partners': all_partners.count(),
        'pending_partners': pending_partners.count(),
        'active_partners': active_partners.count(),
        'pending_partners_list': pending_partners,
        'active_partners_list': active_partners,
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
    
    context = {
        'partner': partner,
        'total_deliveries': total_deliveries,
        'completed_deliveries': completed_deliveries,
        'on_time_percentage': round(on_time_percentage, 2),
        'recent_deliveries': deliveries.order_by('-created_at')[:10],
        'ratings': DeliveryRating.objects.filter(delivery_partner=partner).order_by('-created_at')[:10],
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
            delivery_partner=request.user.deliverypartner
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
            delivery.delivery_partner.save(update_fields=['is_available'])
        
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
                title=f'Delivery Status Update - Order #{delivery.order.id}',
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
    delivery = get_object_or_404(Delivery, id=delivery_id, delivery_partner=request.user.deliverypartner)
    delivery.mark_as_delivered()
    return JsonResponse({'success': True})

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
    delivery_partner = request.user.deliverypartner
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
            user = form.save(commit=False)
            user.user_type = 'delivery_partner'
            user.save()
            
            # Create DeliveryPartner profile
            DeliveryPartner.objects.create(
                user=user,
                vehicle_type=request.POST.get('vehicle_type', ''),
                vehicle_number=request.POST.get('vehicle_number', ''),
                license_number=request.POST.get('license_number', ''),
                license_image=request.FILES.get('license_image'),
                id_proof=request.FILES.get('id_proof'),
                status='pending'  # Set initial status as pending
            )
            
            messages.success(request, 'Registration successful. Please wait for admin approval.')
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
    delivery_partner = request.user.deliverypartner
    
    # Get all completed deliveries
    completed_deliveries = Delivery.objects.filter(
        delivery_partner=delivery_partner,
        status='delivered'
    ).select_related('order')
    
    # Calculate earnings with proper profit sharing
    total_earnings = 0
    delivery_details = []
    
    for delivery in completed_deliveries:
        order = delivery.order
        order_total = float(order.total_price)
        
        # Calculate profit shares
        artisan_share = order_total * 0.70  # 70% to artisan
        platform_fee = order_total * 0.10   # 10% platform fee
        delivery_share = order_total * 0.20  # 20% to delivery partner
        
        # Calculate delivery fee
        base_delivery_fee = 50  # Base delivery fee in rupees
        
        # Calculate time-based fee
        if delivery.actual_delivery_time and delivery.created_at:
            delivery_time = (delivery.actual_delivery_time - delivery.created_at).total_seconds() / 3600  # Convert to hours
            distance_fee = delivery_time * 10  # ₹10 per hour
        else:
            distance_fee = 0
            
        total_delivery_fee = base_delivery_fee + distance_fee
        
        # Total earnings for this delivery
        delivery_total = delivery_share + total_delivery_fee
        total_earnings += delivery_total
        
        # Store delivery details
        delivery_details.append({
            'order_id': order.id,
            'order_total': order_total,
            'delivery_share': delivery_share,
            'delivery_fee': total_delivery_fee,
            'total': delivery_total,
            'timestamp': delivery.actual_delivery_time,
            'rating': delivery.ratings.aggregate(Avg('rating'))['rating__avg'] or 0
        })
    
    # Get monthly earnings breakdown
    monthly_earnings = completed_deliveries.annotate(
        month=TruncMonth('created_at')
    ).values('month').annotate(
        total_orders=Count('id'),
        base_earnings=Sum(
            ExpressionWrapper(
                F('order__total_price') * 0.20,  # 20% of order total
                output_field=DecimalField(max_digits=10, decimal_places=2)
            )
        ),
        delivery_fees=Sum(
            ExpressionWrapper(
                50 + (ExpressionWrapper(
                    F('actual_delivery_time') - F('created_at'),
                    output_field=DurationField()
                ) / timedelta(hours=1) * 10),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            )
        ),
        avg_rating=Avg('ratings__rating')
    ).annotate(
        total_earnings=F('base_earnings') + F('delivery_fees')
    ).order_by('-month')
    
    # Calculate performance metrics
    performance_metrics = {
        'total_deliveries': completed_deliveries.count(),
        'avg_rating': completed_deliveries.aggregate(
            avg_rating=Avg('ratings__rating')
        )['avg_rating'] or 0,
        'on_time_deliveries': completed_deliveries.filter(
            actual_delivery_time__lte=F('expected_delivery_time')
        ).count(),
        'total_earnings': total_earnings,
        'avg_earnings_per_delivery': total_earnings / completed_deliveries.count() if completed_deliveries.count() > 0 else 0
    }
    
    context = {
        'performance_metrics': performance_metrics,
        'monthly_earnings': monthly_earnings,
        'delivery_details': sorted(delivery_details, key=lambda x: x['timestamp'] or timezone.now(), reverse=True),
        'active_delivery': get_active_delivery(delivery_partner)
    }
    
    return render(request, 'delivery_earnings.html', context)

@login_required
@user_passes_test(is_delivery_partner)
def process_delivery_earnings(request, delivery_id):
    """Process earnings for a completed delivery."""
    try:
        delivery = get_object_or_404(
            Delivery.objects.select_related('order', 'delivery_partner'),
            id=delivery_id,
            delivery_partner=request.user.deliverypartner,
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
    partners = DeliveryPartner.objects.filter(status='pending')
    context = {
        'partners': partners
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
            messages.success(request, f'Delivery partner {partner.user.get_full_name()} has been approved.')
        elif action == 'reject':
            partner.status = 'rejected'
            messages.warning(request, f'Delivery partner {partner.user.get_full_name()} has been rejected.')
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
        status='active'
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
    styles.add(ParagraphStyle(name='Center', alignment=1))
    styles.add(ParagraphStyle(name='Right', alignment=2))

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
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
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

    table = Table(data, colWidths=[2.5*inch, 1.5*inch, 1*inch, 1*inch, 1*inch])
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
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
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
    delivery_partner = get_object_or_404(DeliveryPartner, user=request.user)
    
    # Get notification data
    unread_notifications_count = request.user.notifications.filter(is_read=False).count()
    recent_notifications = request.user.notifications.all()[:5]  # Get 5 most recent notifications
    
    # Get active deliveries
    deliveries = Delivery.objects.filter(
        delivery_partner=delivery_partner
    ).exclude(
        status='delivered'
    ).order_by('-created_at')
    
    # Get delivery statistics
    total_deliveries = Delivery.objects.filter(delivery_partner=delivery_partner).count()
    completed_deliveries = Delivery.objects.filter(
        delivery_partner=delivery_partner,
        status='delivered'
    ).count()
    in_transit_deliveries = Delivery.objects.filter(
        delivery_partner=delivery_partner,
        status='in_transit'
    ).count()
    
    # Calculate earnings
    total_earnings = DeliveryRating.objects.filter(
        delivery_partner=delivery_partner,
        delivery__status='delivered'
    ).aggregate(
        total=Sum('delivery__order__total_price')
    )['total'] or 0
    
    context = {
        'delivery_partner': delivery_partner,
        'deliveries': deliveries,
        'total_deliveries': total_deliveries,
        'completed_deliveries': completed_deliveries,
        'in_transit_deliveries': in_transit_deliveries,
        'total_earnings': total_earnings,
        # Add notification data to context
        'unread_notifications_count': unread_notifications_count,
        'recent_notifications': recent_notifications,
    }
    
    return render(request, 'delivery_dashboard.html', context)

@login_required
@user_passes_test(is_delivery_partner)
def delivery_history(request):
    delivery_partner = request.user.deliverypartner
    
    # Get all deliveries for this partner
    deliveries = Delivery.objects.filter(
        delivery_partner=delivery_partner
    ).order_by('-created_at')
    
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
    total_earnings = deliveries.filter(status='delivered').aggregate(
        Sum('order__total_price'))['order__total_price__sum'] or 0
    
    # Get delivery ratings
    ratings = DeliveryRating.objects.filter(
        delivery_partner=delivery_partner
    ).select_related('delivery')
    
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

@login_required
@user_passes_test(is_delivery_partner)
def delivery_tracking(request, delivery_id):
    delivery = get_object_or_404(Delivery, id=delivery_id)
    
    # Ensure the delivery partner can only track their assigned deliveries
    if delivery.delivery_partner.user != request.user:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'message': "You are not authorized to track this delivery."
            })
        messages.error(request, "You are not authorized to track this delivery.")
        return redirect('delivery_dashboard')
    
    # Check if delivery is active
    if delivery.status in ['delivered', 'cancelled']:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'message': "This delivery is no longer active."
            })
        messages.warning(request, "This delivery is no longer active.")
        return redirect('delivery_dashboard')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'update_status':
            new_status = request.POST.get('status')
            notes = request.POST.get('notes', '')
            
            if new_status in dict(Delivery.STATUS_CHOICES):
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
                Notification.objects.create(
                    user=delivery.order.user,
                    title='Delivery Update',
                    message=f'Your order #{delivery.order.id} is {new_status}',
                    notification_type='delivery_update'
                )
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    response_data = {
                        'success': True,
                        'message': f'Delivery status updated to {new_status}',
                        'status': new_status,
                        'status_display': delivery.get_status_display(),
                    }
                    
                    if new_status == 'delivered':
                        delivery.mark_as_delivered()
                        response_data['redirect'] = reverse('delivery_dashboard')
                    
                    return JsonResponse(response_data)
                
                messages.success(request, f'Delivery status updated to {new_status}')
                
                if new_status == 'delivered':
                    delivery.mark_as_delivered()
                    return redirect('delivery_dashboard')
            else:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'message': 'Invalid status value provided.'
                    })
                messages.error(request, 'Invalid status value provided.')
    
    # Get status history
    status_history = delivery.status_history.all().order_by('-timestamp')
    
    context = {
        'delivery': delivery,
        'status_history': status_history,
        'status_choices': [
            status for status in Delivery.STATUS_CHOICES 
            if status[0] not in ['cancelled', 'failed']
        ],
        'active_delivery': delivery,
        'order_items': delivery.order.items.all(),
    }
    
    return render(request, 'delivery_tracking.html', context)

@login_required
@user_passes_test(is_delivery_partner)
def delivery_order_details(request, delivery_id):
    delivery = get_object_or_404(Delivery, id=delivery_id)
    
    # Ensure the delivery partner can only view their assigned deliveries
    if delivery.delivery_partner.user != request.user:
        messages.error(request, "You are not authorized to view this delivery.")
        return redirect('delivery_dashboard')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        notes = request.POST.get('notes', '')
        
        if action == 'update_status':
            new_status = request.POST.get('status')
            if new_status in dict(Delivery.STATUS_CHOICES):
                old_status = delivery.status
                delivery.status = new_status
                delivery.save()
                
                # Create status history entry
                DeliveryStatusHistory.objects.create(
                    delivery=delivery,
                    status=new_status,
                    notes=notes
                )
                
                # Update order status based on delivery status
                if new_status == 'picked_up':
                    delivery.order.status = 'shipped'
                elif new_status == 'delivered':
                    delivery.order.status = 'delivered'
                    delivery.order.delivered_at = timezone.now()
                delivery.order.save()
                
                # Create notifications
                Notification.objects.create(
                    user=delivery.order.user,
                    title='Delivery Status Update',
                    message=f'Your order #{delivery.order.id} status has been updated to {new_status}',
                    notification_type='delivery_update'
                )
                
                messages.success(request, f'Delivery status updated to {new_status}')
                
                # If delivered, update delivery partner availability
                if new_status == 'delivered':
                    delivery.delivery_partner.is_available = True
                    delivery.delivery_partner.save()
                    
                    # Create notification for customer to rate delivery
                    Notification.objects.create(
                        user=delivery.order.user,
                        title='Rate Your Delivery',
                        message=f'Please rate your delivery experience for order #{delivery.order.id}',
                        notification_type='delivery_rating_request'
                    )
        
        elif action == 'add_note':
            DeliveryStatusHistory.objects.create(
                delivery=delivery,
                status=delivery.status,
                notes=notes
            )
            messages.success(request, 'Delivery note added successfully')
    
    # Get status history
    status_history = delivery.status_history.all().order_by('-timestamp')
    
    # Get order items
    order_items = delivery.order.items.all()
    
    context = {
        'delivery': delivery,
        'status_history': status_history,
        'order_items': order_items,
        'status_choices': Delivery.STATUS_CHOICES,
        'active_delivery': delivery if delivery.status not in ['delivered', 'cancelled'] else None,
    }
    
    return render(request, 'delivery_order_details.html', context)

@login_required
@require_POST
def classify_image(request):
    try:
        if 'image' not in request.FILES:
            return JsonResponse({'error': 'No image file provided'}, status=400)
        
        image_file = request.FILES['image']
        
        # Open and convert image to RGB
        image = Image.open(image_file).convert('RGB')
        
        # Get the image classifier (using the cached function)
        processor, model = get_image_classifier()
        
        # Process the image
        inputs = processor(images=image, return_tensors="pt")
        
        # Get model predictions
        with torch.no_grad():
            outputs = model(**inputs)
            logits = outputs.logits
            
            # Get probabilities
            probabilities = torch.nn.functional.softmax(logits, dim=-1)[0]
            
            # Get top 5 predictions
            top_5_probs, top_5_indices = torch.topk(probabilities, 5)
            
            # Convert predictions to list of (probability, class_name) tuples
            predictions = []
            for prob, idx in zip(top_5_probs, top_5_indices):
                class_name = model.config.id2label[idx.item()]
                predictions.append((float(prob), class_name))
            
            # Map the predictions to our custom categories
            predicted_category = Product.map_prediction_to_category(predictions)
            
            # Get the confidence score for the top prediction
            confidence = float(top_5_probs[0]) * 100
            
            # Log the prediction details
            logger.info(f"Image classification - Category: {predicted_category}, Confidence: {confidence:.2f}%")
            logger.info(f"Top 5 predictions: {predictions}")
            
            if confidence < 1 or confidence > 100:
                logger.error(f"Invalid confidence score: {confidence}")
                raise ValueError("Invalid confidence score calculated")
            
            return JsonResponse({
                'success': True,
                'classification': predicted_category,
                'confidence': round(confidence, 2),
                'top_predictions': [
                    {'class': pred[1], 'confidence': round(float(pred[0]) * 100, 2)}
                    for pred in predictions
                ]
            })
            
    except ValueError as ve:
        logger.error(f"Value error in image classification: {str(ve)}")
        return JsonResponse({
            'success': False,
            'error': 'Invalid classification result',
            'details': str(ve)
        }, status=400)
    except Exception as e:
        logger.error(f"Error in image classification: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': 'Failed to process image',
            'details': str(e)
        }, status=500)

@login_required
def notifications(request):
    """View to display all notifications for a user."""
    notifications = request.user.notifications.all().order_by('-created_at')
    
    if request.GET.get('format') == 'json':
        return JsonResponse({
            'notifications': [{
                'id': n.id,
                'title': n.title,
                'message': n.message,
                'created_at': n.created_at.isoformat(),
                'is_read': n.is_read
            } for n in notifications]
        })
    
    context = {
        'notifications': notifications,
        'page_title': 'Notifications'
    }
    return render(request, 'notifications.html', context)

@login_required
def unread_notifications_count(request):
    """Get the count of unread notifications for a user."""
    count = request.user.notifications.filter(is_read=False).count()
    return JsonResponse({'count': count})

@login_required
@require_POST
def mark_notification_read(request, notification_id):
    """Mark a specific notification as read."""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    notification.is_read = True
    notification.save()
    return JsonResponse({'success': True})

@login_required
@require_POST
def mark_all_notifications_read(request):
    """Mark all notifications as read for a user."""
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return JsonResponse({'success': True})

@login_required
@user_passes_test(lambda u: u.is_staff)
def unassigned_orders(request):
    """View to display orders that need delivery assignment."""
    orders = Order.objects.filter(
        status='confirmed',
        delivery__isnull=True
    ).select_related('user__profile').order_by('-created_at')

    context = {
        'orders': orders,
        'page_title': 'Unassigned Orders'
    }
    return render(request, 'unassigned_orders.html', context)

@login_required
@user_passes_test(lambda u: u.is_staff)
def update_delivery_status(request, delivery_id):
    """View to update delivery status."""
    if not (request.user.is_staff or is_delivery_partner(request.user)):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    delivery = get_object_or_404(Delivery, id=delivery_id)
    
    if request.method == 'POST':
        new_status = request.POST.get('status')
        notes = request.POST.get('notes', '')
        
        if new_status in dict(Delivery.STATUS_CHOICES):
            try:
                with transaction.atomic():
                    # Update delivery status
                    delivery.status = new_status
                    if new_status == 'delivered':
                        delivery.actual_delivery_time = timezone.now()
                    delivery.save()
                    
                    # Create status history
                    DeliveryStatusHistory.objects.create(
                        delivery=delivery,
                        status=new_status,
                        notes=notes
                    )
                    
                    # Update order status if delivered
                    if new_status == 'delivered':
                        delivery.order.status = 'delivered'
                        delivery.order.save()
                    
                    # Create notification for customer
                    Notification.objects.create(
                        user=delivery.order.user,
                        title='Delivery Update',
                        message=f'Your order #{delivery.order.id} status has been updated to {new_status}'
                    )
                    
                    return JsonResponse({'success': True})
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)
        else:
            return JsonResponse({'error': 'Invalid status'}, status=400)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)

import csv
@login_required
@user_passes_test(lambda u: u.is_staff)
def export_unassigned_orders(request):
    """Export unassigned orders to CSV/Excel"""
    # Get unassigned orders
    orders = Order.objects.filter(
        status='confirmed',
        delivery__isnull=True
    ).select_related('user__profile')

    # Create the HttpResponse object with CSV header
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="unassigned_orders.csv"'

    # Create CSV writer
    writer = csv.writer(response)
    writer.writerow([
        'Order ID',
        'Customer Name',
        'Email',
        'Address',
        'City',
        'State',
        'Order Date',
        'Total Amount'
    ])

    # Write data rows
    for order in orders:
        writer.writerow([
            order.id,
            order.user.get_full_name(),
            order.user.email,
            order.user.profile.street_address,
            order.user.profile.city,
            order.user.profile.state,
            order.created_at.strftime('%Y-%m-%d %H:%M'),
            order.total_price
        ])

    return response

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
            )
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
            avg_rating=Avg('delivery_ratings__rating')
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
            avg_rating=Avg('delivery_ratings__rating')
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
            avg_rating=Avg('delivery_ratings__rating')
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
    avg_rating = DeliveryRating.objects.filter(
        delivery_partner=partner
    ).aggregate(Avg('rating'))['rating__avg'] or 0
    
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
                message=f'You have been assigned to deliver order #{delivery.order.id}',
                notification_type='delivery_assignment'
            )
            
            Notification.objects.create(
                user=delivery.order.user,
                title='Delivery Update',
                message=f'Your delivery has been reassigned to a new delivery partner',
                notification_type='delivery_update'
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
                    status='processed',
                    processed_at=timezone.now()
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
            
        return JsonResponse({
            'success': True,
            'message': 'Earnings marked as paid successfully'
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)