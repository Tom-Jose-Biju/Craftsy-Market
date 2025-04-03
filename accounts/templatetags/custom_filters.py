from django import template
from django.db.models import Avg
from django.template.defaultfilters import stringfilter

register = template.Library()

@register.filter(name='avg')
def avg(queryset, field_name):
    return queryset.aggregate(Avg(field_name))['rating__avg']

@register.filter
@stringfilter
def truncate_chars(value, max_length):
    if len(value) > max_length:
        return value[:max_length] + '...'
    return value

@register.filter
def get_item(dictionary, key):
    """
    Get an item from a dictionary using the key.
    Usage: {{ my_dict|get_item:key_var }}
    """
    if not dictionary:
        return None
    
    # Convert key to int if it's a string representing a number
    if isinstance(key, str) and key.isdigit():
        key = int(key)
        
    try:
        return dictionary.get(key)
    except (AttributeError, KeyError, TypeError):
        return None