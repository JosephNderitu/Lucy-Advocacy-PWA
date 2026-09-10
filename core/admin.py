from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import path, reverse

from .models import NewsletterCampaign, NewsletterSubscriber, PracticeArea, Conversation, ChatMessage
from .newsletter_utils import make_unsubscribe_token, get_newsletter_connection


@admin.register(PracticeArea)
class PracticeAreaAdmin(admin.ModelAdmin):
    list_display = ("title", "order", "is_active")
    list_editable = ("order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title", "description")
    ordering = ("order",)
    

# ---------------------------------------------------------------------------
# ContactMessage — read-only inbox
# ---------------------------------------------------------------------------
    
import json
from django.http import JsonResponse
from django.utils import timezone
from django.utils.html import format_html


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('email', 'name', 'unread_badge', 'message_count', 'last_message_display')
    search_fields = ('email', 'name')
    ordering = ('-last_message_at',)
    change_form_template = 'admin/core/conversation/change_form.html'
    fields = ('email', 'name')

    @admin.display(description='')
    def unread_badge(self, obj):
        count = obj.unread_count
        if count == 0:
            return ''
        return format_html(
            '<span style="background:#DC2626; color:#fff; font-weight:bold; '
            'font-size:11px; padding:2px 9px; border-radius:999px;">{} new</span>',
            count,
        )

    @admin.display(description='Messages')
    def message_count(self, obj):
        return obj.messages.count()

    @admin.display(description='Last Activity', ordering='last_message_at')
    def last_message_display(self, obj):
        return obj.last_message_at.strftime('%b %d, %Y %H:%M')

    def get_urls(self):
        custom = [
            path(
                '<int:conversation_id>/send-reply/',
                self.admin_site.admin_view(self.send_reply),
                name='public_site_conversation_send_reply',
            ),
        ]
        return custom + super().get_urls()

    def change_view(self, request, object_id, form_url='', extra_context=None):
        conversation = self.get_object(request, object_id)

        # Opening the page marks it read — GET only, so it doesn't
        # fire again on the POST that follows a form save.
        if conversation and request.method == 'GET':
            conversation.admin_read_at = timezone.now()
            conversation.save(update_fields=['admin_read_at'])

        extra_context = extra_context or {}
        extra_context['conversation'] = conversation
        extra_context['chat_messages'] = (
            conversation.messages.order_by('created_at') if conversation else []
        )
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def send_reply(self, request, conversation_id):
        if request.method != 'POST':
            return JsonResponse({'error': 'POST required'}, status=405)
        if not self.has_change_permission(request):
            return JsonResponse({'error': 'Permission denied'}, status=403)

        conversation = self.get_object(request, conversation_id)
        if not conversation:
            return JsonResponse({'error': 'Conversation not found'}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid request'}, status=400)

        body = data.get('body', '').strip()
        if not body:
            return JsonResponse({'error': 'Message cannot be empty'}, status=400)

        msg = ChatMessage.objects.create(conversation=conversation, sender='staff', body=body)

        # Replying obviously means they've seen it too
        conversation.admin_read_at = timezone.now()
        conversation.save(update_fields=['admin_read_at'])

        return JsonResponse({
            'success': True,
            'message': {
                'sender': msg.sender,
                'body': msg.body,
                'created_at': msg.created_at.strftime('%b %d, %H:%M'),
            },
        })

class CampaignForm(forms.Form):
    subject = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "vTextField",
            "placeholder": "e.g. A note on our new Family Law desk",
        }),
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={
            "rows": 12,
            "class": "vLargeTextField",
            "placeholder": "Plain text. Leave a blank line between paragraphs.",
        }),
    )


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "is_active", "subscribed_at", "unsubscribed_at")
    list_filter = ("is_active",)
    search_fields = ("email",)
    change_list_template = "admin/core/newslettersubscriber/change_list.html"

    def get_urls(self):
        return [
            path("send-campaign/", self.admin_site.admin_view(self.send_campaign), name="newsletter_send_campaign"),
        ] + super().get_urls()

    def send_campaign(self, request):
        active_subscribers = NewsletterSubscriber.objects.filter(is_active=True)

        if request.method == "POST":
            form = CampaignForm(request.POST)
            if form.is_valid():
                subject = form.cleaned_data["subject"]
                body = form.cleaned_data["message"]
                connection = get_newsletter_connection()
                connection.open()
                sent = 0

                try:
                    for subscriber in active_subscribers:
                        token = make_unsubscribe_token(subscriber.id)
                        unsubscribe_url = request.build_absolute_uri(
                            reverse("core:newsletter_unsubscribe", args=[token])
                        )
                        html_content = render_to_string("emails/newsletter_campaign.html", {
                            "subject": subject,
                            "message": body,
                            "unsubscribe_url": unsubscribe_url,
                            "site_url": request.build_absolute_uri("/"),
                            "logo_url": request.build_absolute_uri(settings.STATIC_URL + "images/static_images/logo-on-teal.png"),
                            "footer_image_url": request.build_absolute_uri(settings.STATIC_URL + "images/lady-justice.jpg"),
                        })
                        email = EmailMultiAlternatives(
                            subject=subject,
                            body=body,
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            to=[subscriber.email],
                            connection=connection,
                        )
                        email.attach_alternative(html_content, "text/html")
                        email.send()
                        sent += 1
                finally:
                    connection.close()

                NewsletterCampaign.objects.create(subject=subject, message=body, recipient_count=sent)
                messages.success(request, f"Campaign sent to {sent} subscriber(s).")
                return redirect("admin:core_newslettersubscriber_changelist")
        else:
            form = CampaignForm()

        context = dict(
            self.admin_site.each_context(request),
            form=form,
            subscriber_count=active_subscribers.count(),
            title="Send Newsletter Campaign",
            opts=self.model._meta,
        )
        return render(request, "admin/core/newslettersubscriber/send_campaign.html", context)

@admin.register(NewsletterCampaign)
class NewsletterCampaignAdmin(admin.ModelAdmin):
    list_display = ("subject", "sent_at", "recipient_count")
    readonly_fields = ("subject", "message", "sent_at", "recipient_count")

    def has_add_permission(self, request):
        return False  # campaigns are only ever created via "Send Campaign"