from django import template
from django.core.cache import cache

from core.models import PROCESS_CACHE_KEY, ProcessSection

register = template.Library()


@register.inclusion_tag("core/_process.html")
def process_section():
    """Usage in any template:  {% load process_tags %}  ...  {% process_section %}"""
    data = cache.get(PROCESS_CACHE_KEY)
    if data is None:
        section = ProcessSection.objects.filter(is_published=True).first()
        steps = list(section.steps.filter(is_active=True)) if section else []
        data = {"section": section, "steps": steps}
        cache.set(PROCESS_CACHE_KEY, data, 3600)  # cleared automatically whenever the admin saves
    return data