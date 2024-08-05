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
from django.views.decorators.http import require_GET

from .forms import ArtisanProfileForm, ProductForm, ProfileForm
from .models import Artisan, Product, ProductImage, Profile, User

stripe.api_key = settings.STRIPE_SECRET_KEY

# Home and Authentication Views
def home(request):
    return render(request, 'home.html')

def register(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        if not name or not email or not password1 or not password2:
            messages.error(request, 'All fields are required.')
            return render(request, 'register.html')

        if password1 != password2:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'register.html')

        try:
            if User.objects.filter(username=name).exists():
                messages.error(request, 'Username already exists.')
                return render(request, 'register.html')

            user = User.objects.create_user(username=name, email=email, password=password1)
            user.save()

            messages.success(request, 'Registration successful. Please log in.')
            return redirect('login')

        except Exception as e:
            messages.error(request, f'Error creating user: {str(e)}')
            return render(request, 'register.html')

    return render(request, 'register.html')

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            if username == 'admin' and password == 'admin':
                return redirect('admin_dashboard')
            elif user.user_type == 'artisan':
                return redirect('artisan')
            else:
                return redirect('home')
        else:
            messages.error(request, 'Invalid username or password')
    return render(request, 'login.html')

def signout(request):
    logout(request)
    return redirect('home')

def logout_view(request):
    logout(request)
    request.session.flush()
    return redirect('home')

# Admin Views
@login_required
def admin_dashboard(request):
    if request.user.username != 'admin':
        return redirect('home')
    
    total_users = User.objects.count()
    total_artisans = User.objects.filter(user_type='artisan').count()
    total_products = Product.objects.count()
    recent_products = Product.objects.order_by('-created_at')[:5]
    
    context = {
        'total_users': total_users,
        'total_artisans': total_artisans,
        'total_products': total_products,
        'recent_products': recent_products,
    }
    return render(request, 'admin_dashboard.html', context)

@login_required
def admin_users(request):
    if request.user.username != 'admin':
        return redirect('home')
    
    users = User.objects.all().order_by('-date_joined')
    context = {
        'users': users,
    }
    return render(request, 'admin_users.html', context)

@login_required
def admin_artisans(request):
    if request.user.username != 'admin':
        return redirect('home')
    
    artisans = User.objects.filter(user_type='artisan').order_by('-date_joined')
    context = {
        'artisans': artisans,
    }
    return render(request, 'admin_artisans.html', context)

# Artisan Views
def artisan_register(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')
        document = request.FILES.get('document')

        if password1 == password2:
            if not User.objects.filter(username=username).exists():
                user = User.objects.create_user(username=username, email=email, password=password1, user_type='artisan')
                login(request, user)
                return redirect('artisan_home')
            else:
                messages.error(request, "Username already exists.")
        else:
            messages.error(request, "Passwords do not match.")
    
    return render(request, 'artisan_register.html')

@login_required
def artisan_home(request):
    if request.user.user_type != 'artisan':
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    return render(request, 'artisan.html')

@login_required
def artisan(request):
    if request.user.user_type != 'artisan':
        return redirect('home')
    
    request.session['is_artisan_page'] = True
    
    context = {
        'user': request.user,
    }
    return render(request, 'artisan.html', context)

@login_required
def artisan_profile(request):
    if request.user.user_type != 'artisan':
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    try:
        artisan = request.user.artisan
    except ObjectDoesNotExist:
        messages.error(request, "Artisan profile not found.")
        return redirect('home')
    
    if request.method == 'POST':
        form = ArtisanProfileForm(request.POST, request.FILES, instance=artisan)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully')
            return redirect('artisan_profile')
    else:
        form = ArtisanProfileForm(instance=artisan)
    
    return render(request, 'accounts/artisan_profile.html', {'artisan': artisan, 'form': form})

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
    
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save(commit=False)
            product.artisan = request.user
            product.save()

            images = request.FILES.getlist('images')
            for i, image in enumerate(images):
                ProductImage.objects.create(
                    product=product,
                    image=image,
                    is_primary=(i == 0)  # Set the first image as primary
                )

            messages.success(request, "Product added successfully!")
            return redirect('artisan_products')
    else:
        form = ProductForm()
    return render(request, 'add_product.html', {'form': form})

def products(request):
    products = Product.objects.all()
    return render(request, 'products.html', {'products': products})

@login_required
def artisan_products(request):
    if request.user.user_type != 'artisan':
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    products = Product.objects.filter(artisan=request.user)
    return render(request, 'artisan_products.html', {'products': products})

@login_required
def update_product(request, product_id):
    if request.user.user_type != 'artisan':
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    product = get_object_or_404(Product, id=product_id, artisan=request.user)
    
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
            messages.error(request, "There was an error updating the product. Please check the form.")
    else:
        form = ProductForm(instance=product)
    
    return render(request, 'update_product.html', {'form': form, 'product': product})

@login_required
def delete_product(request, product_id):
    if request.user.user_type != 'artisan':
        messages.error(request, "You don't have access to this page.")
        return redirect('home')
    
    product = get_object_or_404(Product, id=product_id, artisan=request.user)
    
    if request.method == 'POST':
        product.delete()
        messages.success(request, "Product deleted successfully!")
        return redirect('artisan_products')
    
    return redirect('artisan_products')

def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    images = product.images.all()
    related_products = Product.objects.filter(category=product.category).exclude(id=product.id)[:4]
    context = {
        'product': product,
        'images': images,
        'related_products': related_products,
    }
    return render(request, 'product_detail.html', context)

# Profile Views
@login_required
def profile(request):
    profile, created = Profile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully')
            return redirect('profile')
    else:
        form = ProfileForm(instance=profile)

    return render(request, 'profile.html', {'form': form, 'profile': profile})

@login_required
def deactivate_account(request):
    if request.method == 'POST':
        user = request.user
        if user.is_superuser and User.objects.filter(is_superuser=True, is_active=True).count() == 1:
            return JsonResponse({'success': False, 'message': 'Cannot deactivate the last active admin account.'})
        user.is_active = False
        user.save()
        logout(request)
        return JsonResponse({'success': True})
    return JsonResponse({'success': False}, status=400)

# Checkout and Payment Views
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
                        'unit_amount': int(product.price * 100),  # Stripe expects amount in cents
                        'product_data': {
                            'name': product.name,
                            'description': product.description[:100],  # Limit description to 100 characters
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

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

@require_GET
def payment_success(request):
    return render(request, 'payment_success.html')

@require_GET
def payment_cancel(request):
    return render(request, 'payment_cancel.html')