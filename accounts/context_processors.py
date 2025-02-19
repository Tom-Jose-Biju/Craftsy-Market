def notifications(request):
    """Context processor to add unread notifications count to all templates."""
    if request.user.is_authenticated:
        unread_notifications_count = request.user.notifications.filter(is_read=False).count()
    else:
        unread_notifications_count = 0
    
    return {
        'unread_notifications_count': unread_notifications_count
    } 