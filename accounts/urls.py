from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.decorators.csrf import ensure_csrf_cookie
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('google-login/', auth_views.LoginView.as_view(template_name='login.html'), name='google-login'),
    path('logout/', views.signout, name='logout'),
    path('profile/', views.profile, name='profile'),
    path('login/', views.login_view, name='login'),

    path('artisan_home/', views.artisan_home, name='artisan_home'),
    path('artisan/register/', views.artisan_register, name='artisan_register'),
    path('artisan/profile/', views.artisan_profile, name='artisan_profile'),
    path('add_product/', views.add_product, name='add_product'),
    path('artisanview/', views.artisanview, name='artisanview'),
    path('artisan_profile/', views.artisan_profile, name='artisan_profile'),
    path('products/', views.products, name='products'),
    path('artisan/products/', views.artisan_products, name='artisan_products'),
    path('artisan/product/update/<int:product_id>/', views.update_product, name='update_product'),
    path('disable_product/<int:product_id>/', views.disable_product, name='disable_product'),
    path('toggle_product_status/<int:product_id>/', views.toggle_product_status, name='toggle_product_status'),
    path('product/<int:product_id>/', views.product_detail, name='product_detail'),
    path('artisan/reviews/', views.artisan_reviews, name='artisan_reviews'),
    path('artisan/orders/', views.artisan_order_details, name='artisan_order_details'),
    path('delete-review/<int:review_id>/', views.delete_review, name='delete_review'),
    path('write-review/<int:order_item_id>/', views.write_review, name='write_review'),

    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-dashboard/users/', views.admin_users, name='admin_users'),
    path('admin-dashboard/artisans/', views.admin_artisans, name='admin_artisans'),
    path('admin-dashboard/products/', views.admin_products, name='admin_products'),
    path('admin-dashboard/add-category/', views.admin_add_category, name='admin_add_category'),
    path('admin-dashboard/edit-category/<int:category_id>/', views.admin_edit_category, name='admin_edit_category'),
    path('admin-dashboard/delete-category/<int:category_id>/', views.admin_delete_category, name='admin_delete_category'),
    path('admin-dashboard/disable-category/<int:category_id>/', views.disable_category, name='admin_disable_category'),
    path('admin-dashboard/enable-category/<int:category_id>/', views.enable_category, name='admin_enable_category'),

    
    path('deactivate-account/', views.deactivate_account, name='deactivate_account'),

    path('checkout/', views.checkout, name='checkout'),
    path('create_checkout_session/', views.create_checkout_session, name='create_checkout_session'),  # Create checkout session
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment/cancel/', views.payment_cancel, name='payment_cancel'),
    
    path('password_reset/', auth_views.PasswordResetView.as_view(template_name='password_reset.html'), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='password_reset_complete.html'), name='password_reset_complete'),

    path('cart/', views.cart, name='cart'),
    path('get_cart/', views.get_cart, name='get_cart'),
    path('remove-from-cart/', views.remove_from_cart, name='remove_from_cart'),
    path('update-cart-quantity/', views.update_cart_quantity, name='update_cart_quantity'),
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
    path('submit-review/<int:order_item_id>/', views.submit_review, name='submit_review'),


    path('blogs/', views.customer_blog_view, name='customer_blog_view'),
    path('artisan/blog/write/', views.artisan_blog_write, name='artisan_blog_write'),
    path('artisan/blog/<int:blog_id>/', views.get_blog_details, name='get_blog_details'),
    path('artisan/blog/<int:blog_id>/delete/', views.delete_blog, name='delete_blog'),
    path('artisan/documents/', views.artisan_documents, name='artisan_documents'),
    path('virtual-try-on/<int:product_id>/', views.virtual_try_on, name='virtual_try_on'),
    path('single-product-checkout/<int:product_id>/', views.single_product_checkout, name='single_product_checkout'),
    path('download-product-report/', views.download_product_report, name='download_product_report'),

    path('order/<int:order_id>/update-status/', views.update_order_status, name='update_order_status'),
    path('order/<int:order_id>/add-tracking/', views.add_tracking_number, name='add_tracking_number'),
    path('order/<int:order_id>/simulate-delivery/', views.simulate_delivery, name='simulate_delivery'),
    path('submit-review/<int:order_item_id>/', views.submit_review, name='submit_review'),
    path('delete-review/<int:review_id>/', views.delete_review, name='delete_review'),
    path('artisan/earnings/', views.artisan_earnings, name='artisan_earnings'),
    path('classify-image/', ensure_csrf_cookie(views.classify_image), name='classify_image'),
    path('blog/<int:blog_id>/like/', views.like_blog, name='like_blog'),
    path('blog/<int:blog_id>/comment/', views.add_comment, name='add_comment'),
    path('blog/<int:blog_id>/comments/', views.get_blog_comments, name='get_blog_comments'),
    path('blog/comment/<int:comment_id>/delete/', views.delete_comment, name='delete_comment'),
    path('download-earnings-report/', views.download_earnings_report, name='download_earnings_report'),
    path('chat/<str:room_name>/', views.chat_room, name='chat_room'),
    path('chat/get_messages/<str:room_name>/', views.get_messages, name='get_messages'),
    path('chat/send_message/<str:room_name>/', views.send_message, name='send_message'),
    path('chat/clear_chat/<str:room_name>/', views.clear_chat, name='clear_chat'),
    path('get-artisan-info/<int:artisan_id>/', views.get_artisan_info, name='get_artisan_info'),
    path('artisan-products/<int:artisan_id>/', views.artisan_products_view, name='artisan_products_view'),
    path('order/<int:order_id>/invoice/', views.download_invoice, name='download_invoice'),

    # Add these new URL patterns
    # path('artisan/sales-forecast/<int:artisan_id>/', views.sales_forecast, name='sales_forecast'),
    
]