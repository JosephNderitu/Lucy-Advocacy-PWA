from django.contrib.sitemaps import Sitemap
from django.urls import reverse

class StaticViewSitemap(Sitemap):
    priority = 0.8
    changefreq = 'weekly'

    def items(self):
        return ['core:home', 'core:about', 'core:contact', 'core:team', 'core:article_list', 'core:privacy_policy']

    def location(self, item):
        return reverse(item)