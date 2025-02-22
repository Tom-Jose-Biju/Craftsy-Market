"""
URL configuration for craftsy project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# project-level urls.py (e.g., craftsy/urls.py)

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),  # Django admin panel URL
    path('', include('accounts.urls')),  # Include accounts URLs at root
    path('oauth/', include('social_django.urls', namespace='social')),
    path('chat/', include('craftsy.routing')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)