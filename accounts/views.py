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
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet
from io import BytesIO
from django.db.models import Sum, Avg, Count
from django.utils import timezone
from django.db.models.functions import TruncMonth
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.views.decorators.csrf import ensure_csrf_cookie
from .models import Comment
from datetime import datetime
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch









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
def admin_artisans(request):
    if not request.user.is_staff:
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    artisans = User.objects.filter(user_type='artisan')
    context = {
        'artisans': artisans,
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
def admin_add_category(request):
    if not request.user.is_staff:
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    if request.method == 'POST':
        category_name = request.POST.get('category_name')
        if category_name:
            Category.objects.create(name=category_name)
            messages.success(request, f"Category '{category_name}' has been added successfully.")
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
        if category_name:
            category.name = category_name
            category.save()
            messages.success(request, f"Category '{category.name}' has been updated successfully.")
            return redirect('admin_add_category')
        else:
            messages.error(request, "Category name cannot be empty.")
    
    return render(request, 'admin_add_category.html', {'category': category})

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

                return JsonResponse({'success': True, 'message': "Product added successfully!"})
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
    products = Product.objects.all()
    categories = Category.objects.filter(is_active=True)  # Only active categories
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
        products = products.filter(price__gte=min_price)

    if max_price:
        products = products.filter(price__lte=max_price)

    for product in products:
        product.reviews_json = json.dumps(list(product.reviews.values('rating')), cls=DjangoJSONEncoder)

    context = {
        'products': products,
        'categories': categories,
        'search_query': search_query,
    }
    
    return render(request, 'products.html', context)

@login_required
def artisan_products(request):
    if request.user.user_type != 'artisan':
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    artisan = get_object_or_404(Artisan, user=request.user)
    products = Product.objects.filter(artisan=artisan)
    return render(request, 'artisan_products.html', {'products': products})

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
def delete_product(request, product_id):
    if request.user.user_type != 'artisan':
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    # Get the Artisan instance
    artisan = get_object_or_404(Artisan, user=request.user)
    
    # Now query the Product using the Artisan instance
    product = get_object_or_404(Product, id=product_id, artisan=artisan)
    
    product.delete()
    messages.success(request, "Product deleted successfully!")
    return redirect('artisan_products')

from django.db.models import Avg
from .models import Review, Product
from .forms import ReviewForm
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages

def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    reviews = product.reviews.all().order_by('-created_at')
    average_rating = reviews.aggregate(Avg('rating'))['rating__avg']

    related_products = Product.objects.filter(category=product.category).exclude(id=product.id)[:3]

    
    context = {
        'product': product,
        'reviews': reviews,
        'average_rating': average_rating,
        'in_stock': product.is_in_stock(),
        'inventory_count': product.inventory,
        'related_products': related_products,
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
                        'currency': 'usd',
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
    context = {
        'wishlist_items': wishlist_items
    }
    return render(request, 'wishlist.html', context)

@login_required
@require_POST
def single_product_checkout(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    if not product.is_in_stock():
        return JsonResponse({'success': False, 'error': 'Product is out of stock'})
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': int(product.price * 100),
                    'product_data': {
                        'name': product.name,
                        'description': product.description[:100],
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.build_absolute_uri(reverse('payment_success')),
            cancel_url=request.build_absolute_uri(reverse('payment_cancel')),
        )
        # Decrease inventory by 1
        product.inventory -= 1
        product.save()
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
        
        cart, created = Cart.objects.get_or_create(user=request.user)
        cart_item, item_created = CartItem.objects.get_or_create(cart=cart, product=product)
        
        if item_created:
            cart_item.quantity = quantity
        else:
            cart_item.quantity += quantity
        
        cart_item.save()
        
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


@login_required
def get_cart(request):
    cart, created = Cart.objects.get_or_create(user=request.user)
    cart_items = []
    for cart_item in cart.items.all():
        cart_items.append({
            'id': cart_item.product.id,
            'name': cart_item.product.name,
            'price': float(cart_item.product.price),
            'quantity': cart_item.quantity,
        })
    return JsonResponse({'cart_items': cart_items})

@login_required
@require_POST
def remove_from_cart(request):
    product_id = request.POST.get('product_id')
    
    if request.user.is_authenticated:
        cart = Cart.objects.get(user=request.user)
        CartItem.objects.filter(cart=cart, product_id=product_id).delete()
    else:
        cart = request.session.get('cart', {})
        if product_id in cart:
            del cart[product_id]
            request.session['cart'] = cart
            request.session.modified = True
    
    return JsonResponse({'success': True})

@login_required
@require_POST
def update_cart_quantity(request):
    product_id = request.POST.get('product_id')
    quantity = int(request.POST.get('quantity', 1))
    
    if request.user.is_authenticated:
        cart = Cart.objects.get(user=request.user)
        try:
            cart_item = CartItem.objects.get(cart=cart, product_id=product_id)
            if quantity > 0:
                cart_item.quantity = quantity
                cart_item.save()
            else:
                cart_item.delete()
        except CartItem.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Product not in cart'})
    else:
        cart = request.session.get('cart', {})
        if product_id in cart:
            if quantity > 0:
                cart[product_id] = quantity
            else:
                del cart[product_id]
            request.session['cart'] = cart
            request.session.modified = True
        else:
            return JsonResponse({'success': False, 'error': 'Product not in cart'})
    
    return JsonResponse({'success': True})

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
    
    # Fetch product data
    products = Product.objects.all().select_related('category', 'artisan__user')
    total_products = products.count()
    total_value = products.aggregate(Sum('price'))['price__sum'] or 0
    average_price = products.aggregate(Avg('price'))['price__avg'] or 0

    # Category analysis
    categories = Category.objects.annotate(product_count=Count('products'))
    
    # Create a PDF buffer
    buffer = BytesIO()
    
    # Create the PDF object
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    title_style = styles['Heading1']
    subtitle_style = styles['Heading2']
    normal_style = styles['Normal']
    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Normal'],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#333333'),
        spaceAfter=12,
        alignment=1  # Center alignment
    )
    table_header_style = ParagraphStyle(
        'TableHeaderStyle',
        parent=styles['Normal'],
        fontSize=12,
        leading=14,
        textColor=colors.black ,
        alignment=1  # Center alignment
    )
    table_cell_style = ParagraphStyle(
        'TableCellStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=12,
        textColor=colors.black,
        alignment=1  # Center alignment
    )
    

    elements.append(Spacer(1, 12))
    elements.append(Paragraph("Craftsy Product Report", header_style))
    elements.append(Paragraph(f"Date: {datetime.now().strftime('%B %d, %Y')}", normal_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#4CAF50')))
    elements.append(Spacer(1, 12))
    
    # Add summary
    elements.append(Paragraph("Summary", subtitle_style))
    summary_data = [
        [Paragraph("Total Products", table_header_style), Paragraph(str(total_products), table_cell_style)],
        [Paragraph("Total Value", table_header_style), Paragraph(f"${total_value:.2f}", table_cell_style)],
        [Paragraph("Average Price", table_header_style), Paragraph(f"${average_price:.2f}", table_cell_style)]
    ]
    summary_table = Table(summary_data, colWidths=[150, 150])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4CAF50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 12))
    
    # Add category analysis
    elements.append(Paragraph("Category Analysis", subtitle_style))
    category_data = [[Paragraph("Category", table_header_style), Paragraph("Product Count", table_header_style)]]
    for category in categories:
        category_data.append([Paragraph(category.name, table_cell_style), Paragraph(str(category.product_count), table_cell_style)])
    category_table = Table(category_data, colWidths=[150, 150])
    category_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2196F3')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(category_table)
    elements.append(Spacer(1, 12))
    
    # Add product list
    elements.append(Paragraph("Product List", subtitle_style))
    product_data = [
        [Paragraph("ID", table_header_style), Paragraph("Name", table_header_style), Paragraph("Category", table_header_style), Paragraph("Price", table_header_style), Paragraph("Inventory", table_header_style), Paragraph("Artisan", table_header_style)]
    ]
    for product in products:
        product_data.append([
            Paragraph(str(product.id), table_cell_style),
            Paragraph(product.name, table_cell_style),
            Paragraph(product.category.name, table_cell_style),
            Paragraph(f"${product.price:.2f}", table_cell_style),
            Paragraph(str(product.inventory), table_cell_style),
            Paragraph(product.artisan.user.username, table_cell_style)
        ])
    product_table = Table(product_data, colWidths=[50, 100, 100, 75, 75, 100])
    product_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#FF9800')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(product_table)
    
    # Build the PDF
    doc.build(elements)
    
    # Make sure you're returning an HttpResponse with the PDF content
    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="product_report.pdf"'
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


import logging

logger = logging.getLogger(__name__)

@ensure_csrf_cookie
@login_required
def classify_image(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST requests are allowed'})

    if 'image' not in request.FILES:
        return JsonResponse({'success': False, 'message': 'No image file provided'})

    image_file = request.FILES['image']
    
    # Check if the file is a JPG
    if not image_file.content_type in ['image/jpeg', 'image/jpg']:
        return JsonResponse({'success': False, 'message': 'Only JPG files are supported'})

    try:
        temp_product = Product()
        category_name = temp_product.classify_image(image_file)
        category, _ = Category.objects.get_or_create(name=category_name)
        
        return JsonResponse({
            'success': True,
            'category': category.name,
            'category_id': category.id
        })
    except Exception as e:
        logger.error(f"Error classifying image: {str(e)}", exc_info=True)
        return JsonResponse({'success': False, 'message': f"Error classifying image: {str(e)}"})

@login_required
def download_earnings_report(request):
    artisan = request.user.artisan
    completed_orders = Order.objects.filter(items__product__artisan=artisan, status='delivered').distinct()
    
    # Fetch earnings data
    total_earnings = completed_orders.aggregate(Sum('total_price'))['total_price__sum'] or 0
    monthly_earnings = completed_orders.filter(created_at__gte=timezone.now() - timezone.timedelta(days=30)).aggregate(Sum('total_price'))['total_price__sum'] or 0
    average_order_value = total_earnings / completed_orders.count() if completed_orders.count() > 0 else 0
    
    # Monthly earnings data for chart
    monthly_earnings_data = list(completed_orders.annotate(month=TruncMonth('created_at')).values('month').annotate(earnings=Sum('total_price')).order_by('month'))
    
    # Top selling products data
    top_products = Product.objects.filter(artisan=artisan).annotate(sales_count=Count('orderitem')).order_by('-sales_count')[:5]
    
    # Create a PDF buffer
    buffer = BytesIO()
    
    # Create the PDF object
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#4a4a4a'),
        spaceAfter=12,
        alignment=1
    )
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Heading2'],
        fontSize=18,
        textColor=colors.HexColor('#6a6a6a'),
        spaceAfter=6,
        alignment=1
    )
    normal_style = styles['Normal']
    
    # Add title and date
    elements.append(Paragraph("Craftsy Artisan Earnings Report", title_style))
    elements.append(Paragraph(f"Generated on: {timezone.now().strftime('%B %d, %Y')}", subtitle_style))
    elements.append(Spacer(1, 0.25*inch))
    
    # Add artisan info
    elements.append(Paragraph(f"Artisan: {artisan.user.get_full_name()}", normal_style))
    elements.append(Paragraph(f"Email: {artisan.user.email}", normal_style))
    elements.append(Spacer(1, 0.25*inch))
    
    # Add summary table
    summary_data = [
        ["Total Earnings", f"${total_earnings:.2f}"],
        ["Monthly Earnings (Last 30 days)", f"${monthly_earnings:.2f}"],
        ["Average Order Value", f"${average_order_value:.2f}"],
        ["Completed Orders", str(completed_orders.count())]
    ]
    summary_table = Table(summary_data, colWidths=[4*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#4a4a4a')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#4a4a4a')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e0e0e0'))
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.25*inch))
    
    # Add monthly earnings chart
    elements.append(Paragraph("Monthly Earnings", subtitle_style))
    monthly_data = [[month['month'].strftime("%B %Y"), f"${month['earnings']:.2f}"] for month in monthly_earnings_data]
    monthly_table = Table([["Month", "Earnings"]] + monthly_data, colWidths=[3*inch, 3*inch])
    monthly_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#4a4a4a')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#4a4a4a')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e0e0e0'))
    ]))
    elements.append(monthly_table)
    elements.append(Spacer(1, 0.25*inch))
    
    # Add top selling products
    elements.append(Paragraph("Top Selling Products", subtitle_style))
    top_products_data = [[product.name, str(product.sales_count)] for product in top_products]
    top_products_table = Table([["Product", "Sales"]] + top_products_data, colWidths=[4*inch, 2*inch])
    top_products_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#4a4a4a')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#4a4a4a')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e0e0e0'))
    ]))
    elements.append(top_products_table)
    
    # Build the PDF
    doc.build(elements)
    
    # FileResponse sets the Content-Disposition header so that browsers
    # present the option to save the file.
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/pdf')