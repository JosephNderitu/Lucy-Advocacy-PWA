"""
URL configuration for lawfirmsite project.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse

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
]

# Custom Error Handlers
handler404 = "core.views.custom_404_view"
handler500 = "core.views.custom_500_view"

# Serve media files in development only
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)