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
    admin_read_at = models.DateTimeField(null=True, blank=True)

    @property
    def unread_count(self):
        qs = self.messages.filter(sender='guest')
        if self.admin_read_at:
            qs = qs.filter(created_at__gt=self.admin_read_at)
        return qs.count()

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
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.core.mail import EmailMultiAlternatives

@receiver(post_save, sender=ChatMessage)
def notify_guest_on_staff_reply(sender, instance, created, **kwargs):
    if not created or instance.sender != 'staff':
        return

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

    if not instance.notified:
        context = {
            'subject': "New reply from Ngima Wangai & Company Advocates",
            'name': instance.conversation.name,
            'message': instance.body,
            'site_url': f"{settings.SITE_URL}/contact/",
            'logo_url': f"{settings.SITE_URL}/static/images/static_images/logo-icon.png",
            'footer_image_url': f"{settings.SITE_URL}/static/images/static_images/logo-icon.png",
        }
        html_body = render_to_string('emails/staff_reply.html', context)

        email = EmailMultiAlternatives(
            subject=context['subject'],
            body=strip_tags(html_body),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[instance.conversation.email],
        )
        email.attach_alternative(html_body, "text/html")
        email.send(fail_silently=True)

        instance.notified = True
        instance.save(update_fields=['notified'])
        
@receiver(post_save, sender=ChatMessage)
def notify_admin_on_guest_message(sender, instance, created, **kwargs):
    if not created or instance.sender != 'guest' or not settings.ADMIN_NOTIFICATION_EMAIL:
        return

    send_mail(
        subject=f"New message from {instance.conversation.name or instance.conversation.email}",
        message=(
            f"{instance.conversation.name or instance.conversation.email} wrote:\n\n"
            f"{instance.body}\n\n"
            f"Reply from the admin panel: {settings.SITE_URL}/admin/core/conversation/{instance.conversation.id}/change/"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[settings.ADMIN_NOTIFICATION_EMAIL],
        fail_silently=True,
    )


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