from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import path, reverse

from .models import *
from .newsletter_utils import make_unsubscribe_token, get_newsletter_connection
import json
from django.http import JsonResponse
from django.utils import timezone
from django.utils.html import format_html


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

class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 1
    fields = ('sender', 'body', 'created_at')
    readonly_fields = ('created_at',)
    ordering = ('created_at',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        recent_ids = qs.order_by('-created_at').values_list('id', flat=True)[:50]
        return qs.filter(id__in=recent_ids)

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
    
# --- REPLACES the previous admin_addition.py content in core/admin.py ---
import random
import string

from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.shortcuts import redirect, get_object_or_404
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.utils.text import slugify

from . import forms as admin_forms  # CaseAdminForm — see admin_forms.py
from .models import ClientProfile, Case, CaseDocument, DocumentRequest, ActivityLog

admin.site.site_header = "Ngima Wangai & Company Advocates — Firm Admin"
admin.site.site_title = "NWC Admin"
admin.site.index_title = "Case Management"


# ---------------------------------------------------------------- helpers --

def generate_unique_username(full_name):
    base = slugify(full_name).replace("-", ".") or "client"
    username, suffix = base, 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f"{base}{suffix}"
    return username


def generate_random_password(length=16):
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


# ------------------------------------------------------- client profile ---
# Kept registered (so its change page still works when opened via the link
# on a Case) but hidden from the admin index — clients are created and
# managed from the Case screen now, not here directly.

@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "id_no", "phone", "created_at")
    search_fields = ("user__username", "user__first_name", "user__last_name", "id_no")

    def has_module_permission(self, request):
        return False


# ------------------------------------------------------------- documents --
# Also hidden from the index — documents are managed as an inline on the
# Case page. Kept registered only so the "Confirm" link/URL works.

class CaseDocumentInline(admin.TabularInline):
    model = CaseDocument
    extra = 0
    fields = ("file", "file_type", "status", "uploaded_by", "uploaded_at", "admin_note", "confirm_link")
    readonly_fields = ("file_type", "uploaded_by", "uploaded_at", "confirm_link")

    def confirm_link(self, obj):
        if not obj.pk:
            return "—"
        if obj.status == "confirmed":
            return mark_safe('<span style="color:#2F7178;font-weight:600;">✓ Confirmed</span>')
        url = reverse("admin:core_casedocument_confirm", args=[obj.pk])
        return format_html(
            '<a class="button" style="background:#3F9199;color:#fff;" href="{}">Confirm</a>', url
        )
    confirm_link.short_description = "Action"


@admin.register(CaseDocument)
class CaseDocumentAdmin(admin.ModelAdmin):
    list_display = ("original_filename", "case", "status", "uploaded_at")

    def has_module_permission(self, request):
        return False

    def get_urls(self):
        return [
            path("<int:pk>/confirm/", self.admin_site.admin_view(self.confirm_view),
                 name="core_casedocument_confirm"),
        ] + super().get_urls()

    def confirm_view(self, request, pk):
        doc = get_object_or_404(CaseDocument, pk=pk)
        doc.status = "confirmed"
        doc.confirmed_by = request.user
        doc.confirmed_at = timezone.now()
        doc.save()
        ActivityLog.objects.create(case=doc.case, actor=request.user, actor_role="admin",
                                    action="confirmed", description=doc.original_filename)
        messages.success(request, f"'{doc.original_filename}' confirmed.")
        return redirect(request.META.get("HTTP_REFERER") or "admin:core_case_changelist")


class DocumentRequestInline(admin.TabularInline):
    model = DocumentRequest
    extra = 1
    fields = ("description", "status", "requested_by", "created_at")
    readonly_fields = ("requested_by", "created_at")


# ------------------------------------------------------------------ case --
# This is the one screen the admin lives in: create a client + case together,
# review/confirm documents, request more, add notes — all in one place.

@admin.register(Case)
class CaseAdmin(admin.ModelAdmin):
    form = admin_forms.CaseAdminForm
    inlines = [CaseDocumentInline, DocumentRequestInline]
    list_display = ("case_number", "title", "client_name", "status_badge", "documents_badge", "created_at")
    list_filter = ("status",)
    search_fields = ("case_number", "title", "client__user__first_name", "client__user__last_name", "client__id_no")
    readonly_fields = ("client_display", "created_by", "created_at")

    class Media:
        css = {"all": ("core/admin/portal_admin.css",)}

    def get_fieldsets(self, request, obj=None):
        if obj:  # editing an existing case — client is already set
            return (
                ("Case", {"fields": ("case_number", "title", "status")}),
                ("Client", {"fields": ("client_display",)}),
                ("Record", {"fields": ("created_by", "created_at")}),
            )
        return (
            ("New client", {
                "fields": ("client_full_name", "client_id_no", "client_phone"),
                "description": (
                    "A portal login is created automatically for this client — "
                    "they'll sign in with the case number below and this ID number. "
                    "No password to set."
                ),
            }),
            ("Case", {"fields": ("case_number", "title", "status")}),
        )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("client__user").annotate(
            pending_count=Count("documents", filter=Q(documents__status="pending"), distinct=True),
            doc_count=Count("documents", distinct=True),
        )

    def save_model(self, request, obj, form, change):
        if not change:
            full_name = form.cleaned_data["client_full_name"].strip()
            id_no = form.cleaned_data["client_id_no"].strip()
            phone = form.cleaned_data.get("client_phone", "").strip()
            first_name, _, last_name = full_name.partition(" ")

            user = User.objects.create_user(
                username=generate_unique_username(full_name),
                password=generate_random_password(),
                first_name=first_name,
                last_name=last_name,
            )
            obj.client = ClientProfile.objects.create(user=user, id_no=id_no, phone=phone)
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for instance in instances:
            if isinstance(instance, DocumentRequest) and not instance.pk:
                instance.requested_by = request.user
                instance.save()
                ActivityLog.objects.create(case=instance.case, actor=request.user, actor_role="admin",
                                            action="requested", description=instance.description)
            else:
                instance.save()
        formset.save_m2m()

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["open_cases"] = Case.objects.filter(status="open").count()
        extra_context["pending_documents"] = CaseDocument.objects.filter(status="pending").count()
        extra_context["pending_requests"] = DocumentRequest.objects.filter(status="pending").count()
        return super().changelist_view(request, extra_context=extra_context)

    # --- display helpers ---

    def client_name(self, obj):
        return obj.client.user.get_full_name() or obj.client.user.username
    client_name.short_description = "Client"
    client_name.admin_order_field = "client__user__first_name"

    def client_display(self, obj):
        if not obj or not obj.client:
            return "—"
        url = reverse("admin:core_clientprofile_change", args=[obj.client.pk])
        name = obj.client.user.get_full_name() or obj.client.user.username
        return format_html('<a href="{}">{}</a> &middot; ID {}', url, name, obj.client.id_no)
    client_display.short_description = "Client"

    def status_badge(self, obj):
        colors = {"open": "#2F7178", "closed": "#6b7280", "on_hold": "#DD6812"}
        color = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="background:{}22;color:{};padding:3px 12px;border-radius:999px;'
            'font-size:12px;font-weight:600;">{}</span>',
            color, color, obj.get_status_display(),
        )
    status_badge.short_description = "Status"

    def documents_badge(self, obj):
        if obj.pending_count:
            return format_html(
                '<span style="background:#fef3c7;color:#92400e;padding:3px 12px;border-radius:999px;'
                'font-size:12px;font-weight:600;">{} pending</span>', obj.pending_count,
            )
        if obj.doc_count:
            return mark_safe('<span style="color:#2F7178;font-weight:600;">✓ all reviewed</span>')
        return mark_safe('<span style="color:#9ca3af;">No documents yet</span>')
    documents_badge.short_description = "Documents"


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("case", "actor_role", "action", "description", "timestamp")
    list_filter = ("actor_role", "action")
    readonly_fields = [f.name for f in ActivityLog._meta.fields]

    def has_add_permission(self, request):
        return False
    

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("name", "rating", "ip_address", "created_at")
    list_filter = ("rating", "created_at")
    search_fields = ("name", "message", "ip_address")
    readonly_fields = ("name", "message", "rating", "ip_address", "edit_token", "created_at")

    def has_add_permission(self, request):
        return False