"""
URL configuration for lawfirmsite project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
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

from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.views.static import serve  # Required for serving local media files in production

# Import custom sitemap view from core
from core.views import custom_sitemap_view


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Disallow: /secure-portal-x8k2-management/",
        "Disallow: /portal/",
        "Disallow: /api/",
        "Sitemap: https://ngimawangaiadvocates.co.ke/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


urlpatterns = [
    # Obfuscated Admin Panel
    path("secure-portal-x8k2-management/", admin.site.urls),
    # SEO Files
    path("robots.txt", robots_txt),
    path("sitemap.xml", custom_sitemap_view, name="custom_sitemap"),
    # Core Application Routes
    path("", include("core.urls")),
    # Serve Media Files (Team member photos, attorney uploads, documents) in production & development
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

# Custom Error Handlers
handler404 = "core.views.custom_404_view"
handler500 = "core.views.custom_500_view"

# Serve static/media files via static helper if DEBUG is active
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)