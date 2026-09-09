from django.db import models

from lawfirmsite import settings
import random
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from datetime import timedelta

def group_name_for_email(email):
    return f"chat_{email.replace('@', '_at_').replace('.', '_dot_')}"

class PracticeArea(models.Model):
    """A single area of legal practice offered by the firm.

    Rendered on the homepage practice-areas grid (and its detail modal).
    Managed through the Django admin so the team can add, reorder, or
    retire a practice area without touching code or redeploying.
    """

    title = models.CharField(max_length=120)
    description = models.TextField()
    icon_class = models.CharField(
        max_length=60,
        help_text="Font Awesome 6 class, e.g. 'fa-solid fa-scale-balanced'.",
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Lower numbers are displayed first.",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Untick to hide this practice area from the site without deleting it.",
    )

    class Meta:
        ordering = ["order", "title"]
        verbose_name = "Practice Area"
        verbose_name_plural = "Practice Areas"

    def __str__(self):
        return self.title
    


class Conversation(models.Model):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Conversation with {self.email}"


class ChatMessage(models.Model):
    SENDER_CHOICES = [('guest', 'Guest'), ('staff', 'Staff')]
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.CharField(max_length=10, choices=SENDER_CHOICES)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    notified = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender}: {self.body[:30]}"


class EmailVerification(models.Model):
    email = models.EmailField()
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_used = models.BooleanField(default=False)

    def is_expired(self):
        return timezone.now() > self.created_at + timedelta(minutes=10)

    def __str__(self):
        return f"{self.email} — {self.code}"


from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


@receiver(post_save, sender=ChatMessage)
def notify_guest_on_staff_reply(sender, instance, created, **kwargs):
    if not created or instance.sender != 'staff':
        return

    # Push it live over WebSocket first, this is what makes it feel instant.
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        group_name_for_email(instance.conversation.email),
        {
            'type': 'chat_message',
            'message': {
                'sender': instance.sender,
                'body': instance.body,
                'created_at': instance.created_at.isoformat(),
            },
        },
    )

    # Still email them too, in case they've closed the tab entirely.
    if not instance.notified:
        send_mail(
            subject="New reply from Ngima Wangai & Company Advocates",
            message=(
                f"Hi {instance.conversation.name or ''},\n\n"
                f"You have a new reply from Ngima Wangai & Company Advocates:\n\n"
                f"\"{instance.body}\"\n\n"
                f"Visit {settings.SITE_URL}/contact/ and verify with this email "
                f"to continue the conversation.\n\n"
                f"Ngima Wangai & Company Advocates"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[instance.conversation.email],
            fail_silently=True,
        )
        instance.notified = True
        instance.save(update_fields=['notified'])


class NewsletterSubscriber(models.Model):
    """A visitor who opted in via the homepage newsletter form.

    Never deleted, even on unsubscribe: is_active distinguishes a
    live subscription from a lapsed one, so the admin keeps a full
    history and a re-signup with the same email reactivates the
    existing record instead of creating a duplicate.
    """

    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-subscribed_at"]
        verbose_name = "Newsletter Subscriber"
        verbose_name_plural = "Newsletter Subscribers"

    def __str__(self):
        return self.email


class NewsletterCampaign(models.Model):
    """A log entry created each time the admin sends a campaign.

    This is a record for reference, nothing reads from it to decide
    who gets emailed next.
    """

    subject = models.CharField(max_length=150)
    message = models.TextField()
    sent_at = models.DateTimeField(auto_now_add=True)
    recipient_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-sent_at"]
        verbose_name = "Newsletter Campaign"
        verbose_name_plural = "Newsletter Campaigns"

    def __str__(self):
        return f"{self.subject} ({self.sent_at:%Y-%m-%d})"