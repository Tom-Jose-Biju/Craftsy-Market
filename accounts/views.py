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
    if not request.user.is_staff:
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    product = get_object_or_404(Product, id=product_id)
    product.delete()
    messages.success(request, f"Product '{product.name}' has been deleted successfully.")
    return JsonResponse({'success': True})

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

def artisan_profile1(request):
    return render(request, 'artisan_profile.html')

# Product Views
@login_required
def add_product(request):
    if request.user.user_type != 'artisan':
        messages.error(request, "Only artisans can add products.")
        return redirect('home')
    
    categories = Category.objects.filter(is_active=True)  # Only active categories

    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            artisan = get_object_or_404(Artisan, user=request.user)
            product.artisan = artisan
            product.save()

            images = request.FILES.getlist('images')
            for i, image in enumerate(images):
                ProductImage.objects.create(
                    product=product,
                    image=image,
                    is_primary=(i == 0)
                )

            messages.success(request, "Product added successfully!")
            return redirect('artisan_products')
    else:
        form = ProductForm()
    return render(request, 'add_product.html', {'form': form, 'categories': categories})

def products(request):
    products = Product.objects.all()
    categories = Category.objects.filter(is_active=True)  # Only active categories

    search_query = request.GET.get('search')
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query) |
            Q(artisan__user__username__icontains=search_query)
        )

    category_id = request.GET.get('category')
    if category_id:
        products = products.filter(category_id=category_id)

   
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
    
    context = {
        'product': product,
        'reviews': reviews,
        'average_rating': average_rating,
    }
    return render(request, 'product_detail.html', context)

@login_required
def artisan_order_details(request):
    artisan = get_object_or_404(Artisan, user=request.user)
    orders = Order.objects.filter(items__product__artisan=artisan).distinct().order_by('-created_at')

    # Pagination
    paginator = Paginator(orders, 10)  # Show 10 orders per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'orders': page_obj,
        'total_orders': orders.count(),
        'pending_orders': orders.filter(status='Processing').count(),
        'completed_orders': orders.filter(status='Delivered').count(),
        'total_revenue': orders.filter(status='Delivered').aggregate(Sum('total_price'))['total_price__sum'] or 0,
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
def add_to_cart(request):
    try:
        product_id = request.POST.get('product_id')
        quantity = int(request.POST.get('quantity', 1))
        
        if not product_id:
            return JsonResponse({'success': False, 'error': 'Product ID is required'})
        
        product = get_object_or_404(Product, id=product_id)
        
        cart, created = Cart.objects.get_or_create(user=request.user)
        cart_item, created = CartItem.objects.get_or_create(cart=cart, product=product)
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
        OrderItem.objects.create(
            order=order,
            product=cart_item.product,
            quantity=cart_item.quantity,
            price=cart_item.product.price
        )

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
def order_detail(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    return render(request, 'order_detail.html', {'order': order})

@login_required
def submit_review(request, order_item_id):
    order_item = get_object_or_404(OrderItem, id=order_item_id, order__user=request.user)
    
    if request.method == 'POST':
        form = ReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.user = request.user
            review.product = order_item.product
            review.save()
            return JsonResponse({'success': True, 'message': 'Your review has been submitted successfully.'})
        else:
            return JsonResponse({'success': False, 'errors': form.errors})
    else:
        form = ReviewForm()
    
    context = {
        'form': form,
        'order_item': order_item,
    }
    return render(request, 'review_modal.html', context)

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

def customer_blog_view(request):
    blogs = Blog.objects.all().order_by('-created_at')
    return render(request, 'customer_blog.html', {'blogs': blogs})

@login_required
@login_required
def artisan_blog_write(request):
    if request.method == 'POST':
        if 'blog_id' in request.POST:  # Edit or Delete operation
            blog_id = request.POST['blog_id']
            blog = get_object_or_404(Blog, id=blog_id, author=request.user)
            
            if 'title' in request.POST:  # Edit operation
                form = BlogForm(request.POST, request.FILES, instance=blog)
                if form.is_valid():
                    form.save()
                    messages.success(request, 'Blog post updated successfully!')
            else:  # Delete operation
                blog.delete()
                messages.success(request, 'Blog post deleted successfully!')
        else:  # New blog post
            form = BlogForm(request.POST, request.FILES)
            if form.is_valid():
                blog = form.save(commit=False)
                blog.author = request.user
                blog.save()
                messages.success(request, 'Blog post created successfully!')
        
        return redirect('artisan_blog_write')
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
    