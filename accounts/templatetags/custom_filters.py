from django import template
from django.db.models import Avg

register = template.Library()

@register.filter(name='avg')
def avg(queryset, field_name):
    return queryset.aggregate(Avg(field_name))['rating__avg']

@register.filter
def get_item(dictionary, key):
    """
    Template filter to get an item from a dictionary using a key.
    Usage: {{ dictionary|get_item:key }}
    """
    return dictionary.get(key)