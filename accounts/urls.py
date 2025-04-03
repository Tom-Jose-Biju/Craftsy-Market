from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.decorators.csrf import ensure_csrf_cookie
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.signout, name='logout'),
    path('profile/', views.profile, name='profile'),

    # Delivery Partner URLs
    path('delivery-partner/register/', views.delivery_partner_register, name='delivery_partner_register'),
    
    # Delivery URLs
    path('delivery/dashboard/', views.delivery_dashboard, name='delivery_dashboard'),
    path('delivery/history/', views.delivery_history, name='delivery_history'),
    path('delivery/ratings/', views.delivery_ratings, name='delivery_ratings'),
    path('delivery/tracking/<int:delivery_id>/', views.view_delivery_tracking, name='delivery_tracking'),
    path('delivery/<int:delivery_id>/update-location/', views.update_delivery_location, name='update_delivery_location'),
    path('delivery/<int:delivery_id>/update-status/', views.update_delivery_status, name='update_delivery_status'),
    path('delivery/<int:delivery_id>/mark-delivered/', views.mark_delivery_delivered, name='mark_delivered'),
    path('delivery/<int:delivery_id>/mark-delivery-delivered/', views.mark_delivery_delivered, name='mark_delivery_delivered'),
    path('delivery/<int:delivery_id>/report-issue/', views.mark_delivery_delivered, name='mark_delivery_issue'),
    path('delivery/<int:delivery_id>/accept/', views.mark_delivery_delivered, name='accept_delivery'),
    path('delivery/earnings/', views.delivery_earnings, name='delivery_earnings'),
    path('delivery/earnings/export/', views.export_earnings, name='export_earnings'),
    path('delivery/profile/', views.delivery_profile, name='delivery_profile'),
    path('delivery/profile/update/', views.delivery_profile, name='update_delivery_profile'),
    path('delivery/<int:delivery_id>/details/', views.delivery_order_details, name='delivery_order_details'),
    path('delivery/<int:delivery_id>/location/', views.get_delivery_location, name='get_delivery_location'),
    path('delivery/<int:delivery_id>/route/', views.get_delivery_route, name='get_delivery_route'),
    path('delivery/history/export/', views.export_delivery_history, name='export_delivery_history'),

    path('artisan_home/', views.artisan_home, name='artisan_home'),
    path('artisan/register/', views.artisan_register, name='artisan_register'),
    path('artisan/profile/', views.artisan_profile, name='artisan_profile'),
    path('add_product/', views.add_product, name='add_product'),
    path('artisanview/', views.artisanview, name='artisanview'),
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
    path('admin-dashboard/unassigned-orders/', views.unassigned_orders, name='unassigned_orders'),
    path('admin-dashboard/add-category/', views.admin_add_category, name='admin_add_category'),
    path('admin-dashboard/edit-category/<int:category_id>/', views.admin_edit_category, name='admin_edit_category'),
    path('admin-dashboard/delete-category/<int:category_id>/', views.admin_delete_category, name='admin_delete_category'),
    path('admin-dashboard/disable-category/<int:category_id>/', views.disable_category, name='admin_disable_category'),
    path('admin-dashboard/enable-category/<int:category_id>/', views.enable_category, name='admin_enable_category'),

    # Delivery Partner Assignment URLs
    path('order/<int:order_id>/select-delivery-partner/', views.select_delivery_partner, name='select_delivery_partner'),
    path('order/<int:order_id>/assign-delivery-partner/<int:partner_id>/', views.assign_delivery_partner, name='assign_delivery_partner'),
    path('order/<int:order_id>/assign-delivery/', views.assign_delivery, name='assign_delivery'),

    path('deactivate-account/', views.deactivate_account, name='deactivate_account'),

    path('checkout/', views.checkout, name='checkout'),
    path('create_checkout_session/', views.create_checkout_session, name='create_checkout_session'),
    path('payment/success/', views.payment_success, name='payment_success'),
    path('payment/cancel/', views.payment_cancel, name='payment_cancel'),
    
    path('password_reset/', auth_views.PasswordResetView.as_view(template_name='password_reset.html'), name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(template_name='password_reset_complete.html'), name='password_reset_complete'),

    path('cart/', views.cart, name='cart'),
    path('add-to-cart/', views.add_to_cart, name='add_to_cart'),
    path('remove-from-cart/', views.remove_from_cart, name='remove_from_cart'),
    path('update-cart-quantity/', views.update_cart_quantity, name='update_cart_quantity'),
    path('get-cart/', views.get_cart, name='get_cart'),
    path('wishlist/', views.wishlist, name='wishlist'),
    path('add-to-wishlist/', views.add_to_wishlist, name='add_to_wishlist'),
    path('remove-from-wishlist/', views.remove_from_wishlist, name='remove_from_wishlist'),
    path('single-product-checkout/<int:product_id>/', views.single_product_checkout, name='single_product_checkout'),
    path('order-history/', views.order_history, name='order_history'),
    path('order_detail/<int:order_id>/', views.view_order_details, name='order_detail'),
    path('order/<int:order_id>/update-status/', views.update_order_status, name='update_order_status'),
    path('order/<int:order_id>/add-tracking/', views.add_tracking_number, name='add_tracking_number'),

    path('blogs/', views.customer_blog_view, name='customer_blog_view'),
    path('artisan/blog/write/', views.artisan_blog_write, name='artisan_blog_write'),
    path('artisan/blog/<int:blog_id>/', views.get_blog_details, name='get_blog_details'),
    path('artisan/blog/<int:blog_id>/delete/', views.delete_blog, name='delete_blog'),
    path('artisan/documents/', views.artisan_documents, name='artisan_documents'),
    path('virtual-try-on/<int:product_id>/', views.virtual_try_on, name='virtual_try_on'),
    path('download-product-report/', views.download_product_report, name='download_product_report'),

    path('submit-review/<int:order_item_id>/', views.submit_review, name='submit_review'),
    path('classify-image/', ensure_csrf_cookie(views.classify_image), name='classify_image'),
    path('blog/<int:blog_id>/like/', views.like_blog, name='like_blog'),
    path('blog/<int:blog_id>/comment/', views.add_comment, name='add_comment'),
    path('blog/<int:blog_id>/comments/', views.get_blog_comments, name='get_blog_comments'),
    path('blog/comment/<int:comment_id>/delete/', views.delete_comment, name='delete_comment'),
    # path('artisan/earnings/', views.artisan_earnings, name='artisan_earnings'),
    path('download-earnings-report/', views.download_earnings_report, name='download_earnings_report'),
    path('chat/<str:room_name>/', views.chat_room, name='chat_room'),
    path('chat/get_messages/<str:room_name>/', views.get_messages, name='get_messages'),
    path('chat/send_message/<str:room_name>/', views.send_message, name='send_message'),
    path('chat/clear_chat/<str:room_name>/', views.clear_chat, name='clear_chat'),
    path('get-artisan-info/<int:artisan_id>/', views.get_artisan_info, name='get_artisan_info'),
    path('artisan-products/<int:artisan_id>/', views.artisan_products_view, name='artisan_products_view'),
    path('order/<int:order_id>/invoice/', views.download_invoice, name='download_invoice'),
    path('admin/delivery-partners/pending/', views.pending_delivery_partners, name='pending_delivery_partners'),
    path('admin/delivery-partners/<int:partner_id>/approve/', views.approve_delivery_partner, name='approve_delivery_partner'),

    # Admin Delivery Partner URLs
    path('admin-delivery-partners/', views.admin_delivery_partners, name='admin_delivery_partners'),
    path('admin-delivery-partners/<int:partner_id>/details/', views.admin_delivery_partner_details, name='admin_delivery_partner_details'),
    path('admin-delivery-partners/<int:partner_id>/suspend/', views.suspend_delivery_partner, name='suspend_delivery_partner'),
    path('admin-delivery-partners/<int:partner_id>/reactivate/', views.reactivate_delivery_partner, name='reactivate_delivery_partner'),
    path('admin-delivery-partners/<int:partner_id>/reset-status/', views.reset_delivery_partner_status, name='reset_delivery_partner_status'),

    # Notification URLs
    path('notifications/', views.notifications, name='notifications'),
    path('notifications/unread-count/', views.unread_notifications_count, name='unread_notifications_count'),
    path('notifications/mark-read/<int:notification_id>/', views.mark_notification_read, name='mark_notification_read'),
    path('notifications/mark-all-read/', views.mark_all_notifications_read, name='mark_all_notifications_read'),
    
    path('admin-dashboard/export-unassigned-orders/',views.export_unassigned_orders, name='export_unassigned_orders'),

    path('rate-delivery/<int:delivery_id>/', views.rate_delivery_form, name='rate_delivery'),

    # Delivery URLs
    path('update-delivery-status/<int:delivery_id>/', views.update_delivery_status, name='update_delivery_status'),
    path('dashboard-update-status/<int:delivery_id>/', views.dashboard_update_status, name='dashboard_update_status'),
    path('simple-update-status/<int:delivery_id>/', views.simple_update_status, name='simple_update_status'),
    path('get-delivery-tracking/<int:delivery_id>/', views.get_delivery_tracking, name='get_delivery_tracking'),
]