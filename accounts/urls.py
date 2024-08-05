from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views  # Import views from the current directory

urlpatterns = [
    path('', views.home, name='home'),  # Home page URL
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.signout, name='logout'),
    path('profile/', views.profile, name='profile'),
    path('artisan_home/', views.artisan_home, name='artisan_home'),  # New URL for the Artisan page
    path('artisan/register/', views.artisan_register, name='artisan_register'),
    path('login/', auth_views.LoginView.as_view(template_name='accounts/login.html'), name='login'),
    path('artisan/profile/', views.artisan_profile, name='artisan_profile'),
    path('profile/', views.profile, name='profile'),
    path('add_product/', views.add_product, name='add_product'),
    path('artisanview/', views.artisanview, name='artisanview'),
    path('artisan_profile1/', views.artisan_profile1, name='artisan_profile1'),
    path('products/', views.products, name='products'),
path('artisan/products/', views.artisan_products, name='artisan_products'),
path('artisan/product/update/<int:product_id>/', views.update_product, name='update_product'),
path('delete_product/<int:product_id>/', views.delete_product, name='delete_product'),
path('artisan/', views.artisan, name='artisan'),
path('product/<int:product_id>/', views.product_detail, name='product_detail'),
path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
path('admin-users/', views.admin_users, name='admin_users'),
path('admin-artisans/', views.admin_artisans, name='admin_artisans'),
path('deactivate-account/', views.deactivate_account, name='deactivate_account'),
path('checkout/', views.checkout, name='checkout'),
path('payment/success/', views.payment_success, name='payment_success'),
path('payment/cancel/', views.payment_cancel, name='payment_cancel'),

    
    

]


