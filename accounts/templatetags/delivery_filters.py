from django import template

register = template.Library()

@register.filter
def get_delivery_rating(ratings, delivery):
    """Get the rating for a specific delivery from a list of ratings"""
    for rating in ratings:
        if rating.delivery == delivery:
            return rating
    return None

@register.filter
def status_color(status):
    """Return Bootstrap color class based on delivery status."""
    status_colors = {
        'pending': 'warning',
        'accepted': 'info',
        'picked_up': 'primary',
        'in_transit': 'primary',
        'near_delivery': 'info',
        'delivered': 'success',
        'failed': 'danger',
        'cancelled': 'secondary'
    }
    return status_colors.get(status.lower(), 'secondary')

@register.filter
def status_icon(status):
    """Return Font Awesome icon class based on delivery status."""
    status_icons = {
        'pending': 'clock',
        'accepted': 'check-circle',
        'picked_up': 'box',
        'in_transit': 'truck',
        'near_delivery': 'map-marker-alt',
        'delivered': 'check-double',
        'failed': 'times-circle',
        'cancelled': 'ban'
    }
    return status_icons.get(status.lower(), 'circle')

@register.filter
def progress_percentage(delivery):
    """Calculate delivery progress percentage."""
    status_weights = {
        'pending': 0,
        'accepted': 20,
        'picked_up': 40,
        'in_transit': 60,
        'near_delivery': 80,
        'delivered': 100,
        'failed': 100,
        'cancelled': 100
    }
    return status_weights.get(delivery.status.lower(), 0)
