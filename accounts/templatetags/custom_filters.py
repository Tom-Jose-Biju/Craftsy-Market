from django import template
from django.db.models import Avg

register = template.Library()

@register.filter(name='avg')
def avg(queryset, field_name):
    return queryset.aggregate(Avg(field_name))['rating__avg']