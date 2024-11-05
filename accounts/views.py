import json

import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .forms import ArtisanProfileForm, ProductForm, ProfileForm
from .models import Artisan, Product, ProductImage, Profile, User
from .forms import UserRegistrationForm
from .models import Order, OrderItem, Product
from .models import Cart, CartItem, Product
from django.dispatch import receiver
from django.db.models.signals import post_save
from django.shortcuts import get_object_or_404
from .models import Category
from django.db.models import Q
from django.views.decorators.http import require_http_methods
from django.db.models import Sum, Avg, Count
from django.core.serializers.json import DjangoJSONEncoder
from django.http import JsonResponse
from .forms import ReviewForm
from .models import OrderItem, Review
from django.core.paginator import Paginator
from .models import Blog
from .forms import BlogForm
from .models import AuthenticityDocument
from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO
from django.db.models import Sum, Avg, Count, F
from django.utils import timezone
from django.db.models.functions import TruncMonth
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.views.decorators.csrf import ensure_csrf_cookie
from .models import Comment
from datetime import datetime
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from .models import ChatMessage
from django.views.decorators.csrf import csrf_exempt
import os
# import tensorflow as tf
from datetime import timedelta
import base64
import matplotlib.pyplot as plt
from django.http import FileResponse
from .models import AuthenticityDocument
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.files.storage import default_storage
import tempfile
import json 











stripe.api_key = settings.STRIPE_SECRET_KEY

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
            else:
                return redirect('home')
        else:
            messages.error(request, 'Invalid username or password')  # Error message for failed login

    return render(request, 'login.html')


@login_required
def signout(request):
    logout(request)
    request.session.flush()
    return redirect('home')

# Admin Views
@login_required
def admin_dashboard(request):
    if not request.user.is_staff:
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    total_users = User.objects.count()
    total_artisans = User.objects.filter(user_type='artisan').count()
    total_products = Product.objects.count()
    recent_products = Product.objects.select_related('artisan').order_by('-created_at')[:5]  # Fetch artisan data
    
    context = {
        'total_users': total_users,
        'total_artisans': total_artisans,
        'total_products': total_products,
        'recent_products': recent_products,
    }
    return render(request, 'admin_dashboard.html', context)

@login_required
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
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            return redirect('profile')  # Redirect to the profile page after saving
    else:
        form = ProfileForm(instance=profile)

    return render(request, 'profile.html', {'form': form, 'profile': profile})

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
    cart, created = Cart.objects.get_or_create(user=request.user)
    cart_items = CartItem.objects.filter(cart=cart)
    
    if not cart_items:
        messages.warning(request, "Your cart is empty.")
        return redirect('home')

    total_price = sum(item.product.price * item.quantity for item in cart_items)

    order = Order.objects.create(
        user=request.user,
        total_price=total_price,
        status='processing'
    )

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
    messages.success(request, "Payment successful! Your order has been placed.")
    return render(request, 'payment_success.html', {'order': order})
    
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
        'can_simulate_delivery': order.status.lower() != 'delivered',
    }
    return render(request, 'order_detail.html', context)

@login_required
def update_order_status(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST' and request.user.is_staff:
        new_status = request.POST.get('status')
        if new_status in dict(Order.STATUS_CHOICES):
            order.status = new_status
            order.save()
            messages.success(request, f"Order status updated to {new_status}")
        else:
            messages.error(request, "Invalid status")
    return redirect('order_detail', order_id=order.id)

@login_required
def add_tracking_number(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST' and request.user.is_staff:
        tracking_number = request.POST.get('tracking_number')
        order.tracking_number = tracking_number
        order.save()
        messages.success(request, "Tracking number added successfully")
    return redirect('order_detail', order_id=order.id)


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
    return response

@login_required
def update_order_status(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status in dict(Order.STATUS_CHOICES):
            order.update_status(new_status)
            messages.success(request, f"Order status updated to {new_status}")
        else:
            messages.error(request, "Invalid status")
    return redirect('order_detail', order_id=order.id)

@login_required
def add_tracking_number(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    if request.method == 'POST':
        tracking_number = request.POST.get('tracking_number')
        order.tracking_number = tracking_number
        order.save()
        messages.success(request, "Tracking number added successfully")
    return redirect('order_detail', order_id=order.id)

@login_required
def simulate_delivery(request, order_id):
    order = get_object_or_404(Order, id=order_id)
    order.simulate_delivery()
    messages.success(request, f"Order status updated to {order.get_status_display()}")
    return redirect('order_detail', order_id=order.id)



from django.core.files.base import ContentFile
from PIL import Image
import numpy as np
import io
from transformers import ViTImageProcessor, ViTForImageClassification
import torch


@ensure_csrf_cookie
@login_required
def classify_image(request):
    if request.method == 'POST' and request.FILES.get('image'):
        image_file = request.FILES['image']
        try:
            # Save the uploaded file temporarily
            temp_path = default_storage.save('temp_image.jpg', ContentFile(image_file.read()))
            
            # Load the ViT model and processor
            processor = ViTImageProcessor.from_pretrained('google/vit-base-patch16-224')
            model = ViTForImageClassification.from_pretrained('google/vit-base-patch16-224')
            
            # Process the image
            with default_storage.open(temp_path) as f:
                img = Image.open(io.BytesIO(f.read())).convert('RGB')
            
            # Prepare the image for the model
            inputs = processor(images=img, return_tensors="pt")
            
            # Get model predictions
            with torch.no_grad():
                outputs = model(**inputs)
                logits = outputs.logits
                predicted_class_idx = logits.argmax(-1).item()
            
            # Map ImageNet classes to your product categories
            category_mapping = {
                'pottery': [
                    'vase', 'pot', 'ceramic', 'earthenware', 'clay', 'porcelain', 'stoneware', 
                    'bowl', 'pitcher', 'planter', 'terracotta', 'pottery wheel', 'glazed', 
                    'ceramic art', 'pottery craft', 'handmade pottery', 'ceramic vessel'
                ],
                'jewelry': [
                    'necklace', 'bracelet', 'ring', 'jewel', 'pendant', 'earring', 'gemstone',
                    'beaded', 'silver', 'gold', 'precious stone', 'chain', 'anklet', 'brooch',
                    'jewelry box', 'ornament', 'pearl', 'diamond', 'handcrafted jewelry'
                ],
                'textiles': [
                    'quilt', 'fabric', 'cloth', 'textile', 'woven', 'embroidery', 'tapestry',
                    'silk', 'cotton', 'wool', 'knitted', 'crochet', 'needlework', 'weaving',
                    'batik', 'tie-dye', 'handloom', 'textile art', 'fabric craft'
                ],
                'woodwork': [
                    'wooden', 'furniture', 'cabinet', 'chair', 'carved', 'carpentry', 'timber',
                    'woodcraft', 'wood carving', 'table', 'shelf', 'hardwood', 'woodworking',
                    'wooden box', 'wood art', 'wooden craft', 'wood turning', 'wooden decor'
                ],
                'paintings': [
                    'art', 'painting', 'canvas', 'artwork', 'oil painting', 'acrylic', 'watercolor',
                    'portrait', 'landscape', 'abstract', 'wall art', 'painted', 'artistic',
                    'brushwork', 'fine art', 'contemporary art', 'modern art', 'traditional painting'
                ],
                'sculptures': [
                    'sculpture', 'statue', 'carving', 'figurine', 'bust', '3D art', 'carved figure',
                    'stone sculpture', 'bronze sculpture', 'modern sculpture', 'abstract sculpture',
                    'decorative sculpture', 'garden statue', 'sculptural art', 'relief sculpture'
                ],
                'metalwork': [
                    'metal', 'bronze', 'iron', 'steel', 'copper', 'brass', 'silverwork',
                    'metalcraft', 'wrought iron', 'metal art', 'forged metal', 'metal sculpture',
                    'decorative metal', 'metal jewelry', 'metalworking', 'hammered metal'
                ],
                'glasswork': [
                    'glass', 'crystal', 'transparent', 'blown glass', 'stained glass', 'glass art',
                    'glass sculpture', 'decorative glass', 'glass vase', 'glass bowl', 'glassware',
                    'fused glass', 'glass bead', 'glass mosaic', 'art glass', 'glass craft'
                ],
                'leatherwork': [
                    'leather', 'bag', 'wallet', 'belt', 'leather craft', 'leather goods',
                    'leather accessory', 'leather purse', 'leather pouch', 'leather journal',
                    'leather case', 'tooled leather', 'leather work', 'handmade leather'
                ],
                'candles': [
                    'candle', 'wax', 'scented candle', 'pillar candle', 'taper candle', 
                    'votive candle', 'soy candle', 'beeswax candle', 'decorative candle',
                    'aromatherapy candle', 'handmade candle', 'candle holder', 'jar candle',
                    'floating candle', 'tea light', 'scented wax', 'candle making'
                ],
                'action_figures': [
                    # Popular Franchises
                    'marvel figure', 'dc figure', 'star wars figure', 'anime figure','batman',
                    'dragon ball figure', 'pokemon figure', 'gundam model', 'transformers figure',
                    
                    # Figure Types
                    'action figure', 'collectible figure', 'statue figure', 'scale figure',
                    'poseable figure', 'articulated figure', 'display figure', 'limited edition figure',
                    
                    # Materials and Features
                    'plastic figure', 'resin figure', 'vinyl figure', 'die-cast figure',
                    'painted figure', 'detailed figure', 'movable joints', 'accessories',
                    
                    # Characters and Themes
                    'superhero', 'robot', 'mecha', 'character', 'warrior', 'monster',
                    'comic book character', 'movie character', 'game character',
                    
                    # Collections and Display
                    'collectible', 'action toy', 'display piece', 'figurine', 'model kit',
                    'diorama', 'collection item', 'boxed figure', 'mint condition'
                ],
                'handicrafts': [
                    'handmade', 'craft', 'ornament', 'decoration', 'artisan craft', 'folk art',
                    'handcrafted', 'traditional craft', 'decorative art', 'craft supply',
                    'handmade decor', 'artistic craft', 'craft work', 'handmade gift',
                    'craft project', 'DIY craft', 'handmade item', 'craft material'
                ]
            }
            
            # Get the predicted ImageNet class
            predicted_class = model.config.id2label[predicted_class_idx]
            
            # Map to your category
            matched_category = None
            confidence = float(logits.softmax(dim=-1)[0][predicted_class_idx])
            
            for category, keywords in category_mapping.items():
                if any(keyword.lower() in predicted_class.lower() for keyword in keywords):
                    matched_category = category
                    break
            
            if not matched_category:
                matched_category = 'handicrafts'  # Default category
            
            # Get category ID from your Product model
            categories = Category.objects.all()
            category_obj = categories.filter(name__iexact=matched_category).first()
            
            if not category_obj:
                category_obj = categories.first()  # Fallback to first category
            
            return JsonResponse({
                'success': True,
                'category': category_obj.name,
                'category_id': category_obj.id,
                'confidence': confidence,
                'predicted_class': predicted_class  # Original ImageNet class for reference
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'message': f"Error: {str(e)}"})
        finally:
            # Clean up the temporary file
            if 'temp_path' in locals():
                default_storage.delete(temp_path)
                
    return JsonResponse({'success': False, 'message': 'Invalid request'})

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
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (-2, -1), (-1, -1), 'RIGHT'),
        ('FONTNAME', (-2, -1), (-1, -1), 'Helvetica-Bold'),
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

from django.db.models.functions import TruncDate
import pandas as pd
from prophet import Prophet
import csv
import plotly.graph_objects as go
import plotly.express as px

@login_required
def sales_forecast(request, artisan_id):
    # Read the CSV file
    csv_file_path = 'artisan_sales_data.csv'
    df = pd.read_csv(csv_file_path)
    
    # Filter data for the specific artisan
    df = df[df['artisan_id'] == artisan_id]
    
    if df.empty:
        context = {
            'error_message': "No sales data available for forecasting.",
        }
        return render(request, 'sales_forecast.html', context)

    # Prepare data for charts
    df['date'] = pd.to_datetime(df['date'])
    df['total_sales'] = df['quantity'] * df['price']
    
    # Convert USD to INR (assuming 1 USD = 75 INR)
    usd_to_inr = 75
    df['total_sales_inr'] = df['total_sales'] * usd_to_inr

    # Stacked area chart for product categories
    category_sales = df.groupby(['date', 'category'])['total_sales_inr'].sum().unstack()
    fig_stacked = px.area(category_sales, x=category_sales.index, y=category_sales.columns,
                          title='Sales by Product Category (INR)')
    chart_stacked = fig_stacked.to_html(full_html=False)

    # Heatmap for daily sales
    daily_sales = df.groupby('date')['total_sales_inr'].sum().reset_index()
    daily_sales['weekday'] = daily_sales['date'].dt.weekday
    daily_sales['week'] = daily_sales['date'].dt.isocalendar().week
    pivot_sales = daily_sales.pivot(index='week', columns='weekday', values='total_sales_inr')
    fig_heatmap = px.imshow(pivot_sales, labels=dict(x="Day of Week", y="Week", color="Sales (INR)"),
                            x=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
                            title='Daily Sales Heatmap (INR)')
    chart_heatmap = fig_heatmap.to_html(full_html=False)

    # Top selling products
    top_products = df.groupby('product_name')['quantity'].sum().sort_values(ascending=False).head(5)

    # Summary statistics
    total_sales = df['total_sales_inr'].sum()
    total_orders = df['quantity'].sum()
    avg_order_value = total_sales / total_orders if total_orders > 0 else 0

    # Growth insights
    last_month = df[df['date'] >= df['date'].max() - pd.Timedelta(days=30)]
    previous_month = df[(df['date'] < df['date'].max() - pd.Timedelta(days=30)) & (df['date'] >= df['date'].max() - pd.Timedelta(days=60))]
    
    last_month_sales = last_month['total_sales_inr'].sum()
    previous_month_sales = previous_month['total_sales_inr'].sum()
    
    growth_rate = ((last_month_sales - previous_month_sales) / previous_month_sales) * 100 if previous_month_sales > 0 else 0

    # Market variations
    category_growth = {}
    for category in df['category'].unique():
        last_month_cat = last_month[last_month['category'] == category]['total_sales_inr'].sum()
        previous_month_cat = previous_month[previous_month['category'] == category]['total_sales_inr'].sum()
        category_growth[category] = ((last_month_cat - previous_month_cat) / previous_month_cat) * 100 if previous_month_cat > 0 else 0

    # Alerts
    alerts = []
    if growth_rate > 20:
        alerts.append({"type": "success", "message": f"Great job! Your sales have grown by {growth_rate:.2f}% in the last month."})
    elif growth_rate < -10:
        alerts.append({"type": "error", "message": f"Alert: Your sales have declined by {abs(growth_rate):.2f}% in the last month."})

    for category, growth in category_growth.items():
        if growth > 30:
            alerts.append({"type": "info", "message": f"The {category} category is showing strong growth at {growth:.2f}%."})
        elif growth < -20:
            alerts.append({"type": "warning", "message": f"The {category} category is underperforming with a {abs(growth):.2f}% decline."})

    context = {
        'chart_stacked': chart_stacked,
        'chart_heatmap': chart_heatmap,
        'top_products': top_products.to_dict(),
        'total_sales': total_sales,
        'total_orders': total_orders,
        'avg_order_value': avg_order_value,
        'growth_rate': growth_rate,
        'category_growth': category_growth,
        'alerts': alerts,
    }
    return render(request, 'sales_forecast.html', context)