"""
Put this next to views.py as core/reviews_support.py (or paste it into views.py / utils.py).
It replaces your existing serialize_review and adds cached review statistics.
"""
from django.core.cache import cache
from django.db.models import Avg, Count, Q
from django.utils import timezone
from django.utils.formats import date_format

from .models import REVIEWS_CACHE_KEY, Review

EDIT_WINDOW_SECONDS = 60


def serialize_review(review, include_private=False):
    data = {
        "id": review.pk,
        "name": review.name,
        "initials": review.initials,
        "message": review.message,
        "rating": review.rating,
        "created_at": date_format(timezone.localtime(review.created_at), "M j, Y"),
    }
    if include_private:  # only ever sent back to the person who just wrote the review
        data["edit_token"] = str(review.edit_token)
        data["seconds_left"] = max(0, EDIT_WINDOW_SECONDS - int((timezone.now() - review.created_at).total_seconds()))
    return data


def review_stats():
    """Average, total and the 5..1 star breakdown in ONE query (was three)."""
    agg = Review.objects.aggregate(
        avg=Avg("rating"),
        total=Count("id"),
        **{f"r{n}": Count("id", filter=Q(rating=n)) for n in range(1, 6)},
    )
    return {
        "avg": round(agg["avg"] or 0, 1),
        "total": agg["total"],
        "breakdown": [agg[f"r{n}"] for n in (5, 4, 3, 2, 1)],  # index 0 is five stars
    }


def home_review_context():
    """Latest 30 reviews plus stats, cached for 5 minutes. Cleared automatically whenever a review is saved or deleted."""
    data = cache.get(REVIEWS_CACHE_KEY)
    if data is None:
        data = {
            "reviews": [serialize_review(r) for r in Review.objects.order_by("-created_at")[:30]],
            "review_stats": review_stats(),
        }
        cache.set(REVIEWS_CACHE_KEY, data, 300)
    return data