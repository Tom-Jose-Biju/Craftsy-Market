from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Profile, User, Category

admin.site.register(User)
admin.site.register(Profile)
admin.site.register(Category)

