from django.contrib.auth import views as auth_views
from django.urls import include, path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.signout, name='logout'),
    path('profile/', views.profile, name='profile'),

    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),

    path('artisan_home/', views.artisan_home, name='artisan_home'),
    path('artisan/register/', views.artisan_register, name='artisan_register'),
    path('artisan/profile/', views.artisan_profile, name='artisan_profile'),
    path('add_product/', views.add_product, name='add_product'),
    path('artisanview/', views.artisanview, name='artisanview'),
    path('artisan_profile1/', views.artisan_profile1, name='artisan_profile1'),
    path('products/', views.products, name='products'),
    path('artisan/products/', views.artisan_products, name='artisan_products'),
    path('artisan/product/update/<int:product_id>/', views.update_product, name='update_product'),
    path('delete_product/<int:product_id>/', views.delete_product, name='delete_product'),
    path('product/<int:product_id>/', views.product_detail, name='product_detail'),

    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-dashboard/users/', views.admin_users, name='admin_users'),
    path('admin-dashboard/artisans/', views.admin_artisans, name='admin_artisans'),
    path('admin-dashboard/add-category/', views.admin_add_category, name='admin_add_category'),

    
    path('deactivate-account/', views.deactivate_account, name='deactivate_account'),
    path('checkout/', views.checkout, name='checkout'),
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment/cancel/', views.payment_cancel, name='payment_cancel'),
    path('password_reset/', auth_views.PasswordResetView.as_view(template_name='password_reset.html'), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='password_reset_complete.html'), name='password_reset_complete'),

    path('cart/', views.cart, name='cart'),
    path('wishlist/', views.wishlist, name='wishlist'),
    path('add-to-cart/', views.add_to_cart, name='add_to_cart'),
    path('remove-from-cart/', views.remove_from_cart, name='remove_from_cart'),
    path('update-cart-quantity/', views.update_cart_quantity, name='update_cart_quantity'),
    path('add-to-wishlist/', views.add_to_wishlist, name='add_to_wishlist'),
    path('remove-from-wishlist/', views.remove_from_wishlist, name='remove_from_wishlist'),
    path('get_cart/', views.get_cart, name='get_cart'),
    path('create_checkout_session/', views.create_checkout_session, name='create_checkout_session'),
    path('payment_success/', views.payment_success, name='payment_success'),
    path('payment_cancel/', views.payment_cancel, name='payment_cancel'),
    path('order-history/', views.order_history, name='order_history'),
    path('order-detail/<int:order_id>/', views.order_detail, name='order_detail'),
]