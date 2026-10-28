from django.contrib.sitemaps import Sitemap
from django.urls import reverse

class StaticViewSitemap(Sitemap):
    priority = 0.8
    changefreq = 'weekly'
    protocol = 'https'

    def items(self):
        return [
            'core:home',
            'core:about',
            'core:contact',
            'core:team',
            'core:article_list',
            'core:privacy_policy',
            'core:terms_conditions',
            'core:cookie_policy'
        ]

    def location(self, item):
        return reverse(item)

    def get_urls(self, site=None, **kwargs):
        # Override to bypass Site matching query database check
        return super().get_urls(site=site, **kwargs)