"""
core/admin.py
=============
"""
import csv
import json
import secrets
import string

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.db.models import Count, F, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.text import slugify

from . import forms as admin_forms  # CaseAdminForm lives in core/forms.py
from .models import (
    ActivityLog, Article, ArticleImage, Case, CaseDocument, ChatMessage,
    ClientProfile, Conversation, DocumentRequest, NewsletterCampaign,
    NewsletterSubscriber, PracticeArea, Review, TeamMember
)
from .newsletter_utils import get_newsletter_connection, make_unsubscribe_token

# =============================================================================
#  BRANDING
#  Site titles used in browser tabs and the login screen.
# =============================================================================
admin.site.site_header = "Ngima Wangai & Company Advocates"
admin.site.site_title = "NWC Admin"
admin.site.index_title = "Firm administration"


# =============================================================================
#  SHARED TOOLKIT
#  One palette and one pill style, so every status across the admin speaks the
#  same visual language. Teal means healthy or complete, amber means needs
#  attention, orange means waiting on someone, grey means closed.
# =============================================================================
TEAL, TEAL_LIGHT, ORANGE = "#2F7178", "#3F9199", "#DD6812"

CASE_PILL = {
    "open": ("#DDEFF0", TEAL),
    "closed": ("#E5E7EB", "#4B5563"),
    "on_hold": ("#FDE8D7", "#B4510C"),
}
DOC_PILL = {
    "pending": ("#FEF3C7", "#92400E"),
    "confirmed": ("#DDEFF0", TEAL),
    "rejected": ("#FEE2E2", "#B91C1C"),
}
AMBER = ("#FEF3C7", "#92400E")
RED = ("#DC2626", "#FFFFFF")


def pill(text, colours):
    """A compact, consistent status badge."""
    bg, fg = colours
    return format_html(
        '<span style="display:inline-block;padding:.22rem .7rem;border-radius:999px;'
        'font-size:.72rem;font-weight:600;letter-spacing:.01em;white-space:nowrap;'
        'background:{};color:{}">{}</span>', bg, fg, text)


def muted(text):
    return format_html('<span style="color:#9CA3AF">{}</span>', text)


def generate_unique_username(full_name):
    """'John Mwangi' becomes 'john.mwangi', with a numeric suffix on collision."""
    base = slugify(full_name).replace("-", ".") or "client"
    username, suffix = base, 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f"{base}{suffix}"
    return username


def generate_random_password(length=20):
    """Cryptographically secure. Clients never see it: they sign in with case number and ID."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _ids(queryset):
    """Primary keys of an (annotated) admin queryset, safe to feed into update()."""
    return queryset.values_list("pk", flat=True)


# =============================================================================
#  1. CLIENT PORTAL
# =============================================================================
@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "id_no", "phone", "created_at")
    search_fields = ("user__username", "user__first_name", "user__last_name", "id_no")

    def has_module_permission(self, request):
        return False


# ---- Case documents ---------------------------------------------------------
class CaseDocumentInline(admin.TabularInline):
    """Evidence on file for a matter, with a one-click confirmation per row."""
    model = CaseDocument
    fk_name = "case"
    extra = 0
    fields = ("file", "file_type", "status", "uploaded_by", "uploaded_at", "admin_note", "confirm_link")
    readonly_fields = ("file_type", "uploaded_by", "uploaded_at", "confirm_link")

    @admin.display(description="Action")
    def confirm_link(self, obj):
        if not obj.pk:
            return muted("Save to enable")
        if obj.status == "confirmed":
            return pill("Confirmed", DOC_PILL["confirmed"])
        url = reverse("admin:core_casedocument_confirm", args=[obj.pk])
        return format_html(
            '<a class="btn btn-sm btn-primary" href="{}">Confirm</a>', url)


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
        """Lock a document as part of the case record and write it to the audit trail."""
        doc = get_object_or_404(CaseDocument, pk=pk)
        if doc.status != "confirmed":
            doc.status = "confirmed"
            doc.confirmed_by = request.user
            doc.confirmed_at = timezone.now()
            doc.save()
            ActivityLog.objects.create(
                case=doc.case, actor=request.user, actor_role="admin",
                action="confirmed", description=doc.original_filename)
            messages.success(request, f"'{doc.original_filename}' confirmed.")
        return redirect(request.META.get("HTTP_REFERER") or "admin:core_case_changelist")


# ---- Document requests ------------------------------------------------------
class DocumentRequestInline(admin.TabularInline):
    """Ask the client for something specific. They see it on their portal."""
    model = DocumentRequest
    fk_name = "case"
    extra = 1
    fields = ("description", "status", "requested_by", "created_at")
    readonly_fields = ("requested_by", "created_at")


# ---- Cases ------------------------------------------------------------------
class AttentionFilter(admin.SimpleListFilter):
    """Triage view: which matters are waiting on the firm, and which on the client."""
    title = "attention"
    parameter_name = "attention"

    def lookups(self, request, model_admin):
        return [("review", "Documents awaiting review"), ("requests", "Awaiting client documents")]

    def queryset(self, request, queryset):
        if self.value() == "review":
            return queryset.filter(pending_count__gt=0)
        if self.value() == "requests":
            return queryset.filter(request_count__gt=0)
        return queryset


@admin.register(Case)
class CaseAdmin(admin.ModelAdmin):
    """The one screen the firm lives in.

    Creating a case also creates the client and their portal login in a single
    step. Opening an existing case shows documents, requests and a record of
    who did what.
    """
    form = admin_forms.CaseAdminForm
    inlines = [CaseDocumentInline, DocumentRequestInline]
    list_display = ("case_number", "title", "client_name", "status_badge",
                    "documents_badge", "requests_badge", "created_at")
    list_filter = (AttentionFilter, "status", ("created_at", admin.DateFieldListFilter))
    search_fields = ("case_number", "title", "client__user__first_name",
                     "client__user__last_name", "client__id_no")
    search_help_text = "Search by case number, title, client name or ID number"
    date_hierarchy = "created_at"
    list_per_page = 25
    save_on_top = True
    readonly_fields = ("client_display", "created_by", "created_at")
    actions = ["close_cases", "reopen_cases", "hold_cases"]

    # ---- form layout --------------------------------------------------------
    def get_fieldsets(self, request, obj=None):
        if obj:  # existing matter: the client is already attached
            return (
                ("Case", {"fields": ("case_number", "title", "status")}),
                ("Client", {"fields": ("client_display",)}),
                ("Record", {"fields": ("created_by", "created_at")}),
            )
        return (  # new matter: capture the client and the case together
            ("New client", {
                "fields": ("client_full_name", "client_id_no", "client_phone"),
                "description": (
                    "A portal login is created automatically for this client. "
                    "They sign in with the case number below and this ID number. "
                    "No password to set."
                ),
            }),
            ("Case", {"fields": ("case_number", "title", "status")}),
        )

    # ---- data ---------------------------------------------------------------
    def get_queryset(self, request):
        """Counts are annotated once so the list never queries per row."""
        return super().get_queryset(request).select_related("client__user").annotate(
            pending_count=Count("documents", filter=Q(documents__status="pending"), distinct=True),
            doc_count=Count("documents", distinct=True),
            request_count=Count("document_requests", filter=Q(document_requests__status="pending"),
                                distinct=True),
        )

    def save_model(self, request, obj, form, change):
        """On creation, build the client user and profile, then attach them to the case."""
        if not change:
            full_name = form.cleaned_data["client_full_name"].strip()
            id_no = form.cleaned_data["client_id_no"].strip()
            phone = form.cleaned_data.get("client_phone", "").strip()
            first_name, _, last_name = full_name.partition(" ")

            user = User.objects.create_user(
                username=generate_unique_username(full_name),
                password=generate_random_password(),
                first_name=first_name, last_name=last_name)
            obj.client = ClientProfile.objects.create(user=user, id_no=id_no, phone=phone)
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        """Stamp new requests and uploads with the acting staff member and log them."""
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for instance in instances:
            is_new = not instance.pk
            if isinstance(instance, DocumentRequest) and is_new:
                instance.requested_by = request.user
                instance.save()
                ActivityLog.objects.create(
                    case=instance.case, actor=request.user, actor_role="admin",
                    action="requested", description=instance.description)
            elif isinstance(instance, CaseDocument) and is_new:
                instance.uploaded_by = request.user
                instance.save()
                ActivityLog.objects.create(
                    case=instance.case, actor=request.user, actor_role="admin",
                    action="uploaded", description=instance.original_filename)
            else:
                instance.save()
        formset.save_m2m()

    def changelist_view(self, request, extra_context=None):
        """Headline numbers for the dashboard strip above the case list."""
        extra_context = extra_context or {}
        extra_context["open_cases"] = Case.objects.filter(status="open").count()
        extra_context["pending_documents"] = CaseDocument.objects.filter(status="pending").count()
        extra_context["pending_requests"] = DocumentRequest.objects.filter(status="pending").count()
        return super().changelist_view(request, extra_context=extra_context)

    # ---- columns ------------------------------------------------------------
    @admin.display(description="Client", ordering="client__user__first_name")
    def client_name(self, obj):
        return obj.client.user.get_full_name() or obj.client.user.username

    @admin.display(description="Client")
    def client_display(self, obj):
        if not obj or not obj.client:
            return "-"
        url = reverse("admin:core_clientprofile_change", args=[obj.client.pk])
        name = obj.client.user.get_full_name() or obj.client.user.username
        return format_html('<a href="{}">{}</a> &middot; ID {}', url, name, obj.client.id_no)

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        return pill(obj.get_status_display(), CASE_PILL.get(obj.status, CASE_PILL["closed"]))

    @admin.display(description="Documents", ordering="pending_count")
    def documents_badge(self, obj):
        if obj.pending_count:
            return pill(f"{obj.pending_count} to review", AMBER)
        if obj.doc_count:
            return pill("All reviewed", DOC_PILL["confirmed"])
        return muted("None yet")

    @admin.display(description="Requests", ordering="request_count")
    def requests_badge(self, obj):
        if obj.request_count:
            return pill(f"{obj.request_count} awaiting client", CASE_PILL["on_hold"])
        return muted("-")

    # ---- bulk actions -------------------------------------------------------
    def _set_status(self, request, queryset, status, label):
        n = Case.objects.filter(pk__in=_ids(queryset)).update(status=status)
        self.message_user(request, f"{n} case(s) {label}.", messages.SUCCESS)

    @admin.action(description="Close selected cases", permissions=["change"])
    def close_cases(self, request, queryset):
        self._set_status(request, queryset, "closed", "closed")

    @admin.action(description="Reopen selected cases", permissions=["change"])
    def reopen_cases(self, request, queryset):
        self._set_status(request, queryset, "open", "reopened")

    @admin.action(description="Put selected cases on hold", permissions=["change"])
    def hold_cases(self, request, queryset):
        self._set_status(request, queryset, "on_hold", "put on hold")


# ---- Activity log -----------------------------------------------------------
@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    """The audit trail. Entries are written by the system and can never be edited or removed here."""
    list_display = ("when", "case", "actor_col", "actor_role", "action", "description")
    list_filter = ("actor_role", "action", ("timestamp", admin.DateFieldListFilter))
    search_fields = ("case__case_number", "description", "actor__username",
                     "actor__first_name", "actor__last_name")
    date_hierarchy = "timestamp"
    list_select_related = ("case", "actor")
    list_per_page = 50
    readonly_fields = [f.name for f in ActivityLog._meta.fields]

    @admin.display(description="When", ordering="timestamp")
    def when(self, obj):
        return obj.timestamp.strftime("%d %b %Y, %H:%M")

    @admin.display(description="Actor")
    def actor_col(self, obj):
        if not obj.actor:
            return muted("System")
        return obj.actor.get_full_name() or obj.actor.username

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# =============================================================================
#  2. CLIENT CONVERSATIONS
# =============================================================================
class UnreadFilter(admin.SimpleListFilter):
    title = "inbox"
    parameter_name = "unread"

    def lookups(self, request, model_admin):
        return [("1", "Unread only")]

    def queryset(self, request, queryset):
        return queryset.filter(unread_n__gt=0) if self.value() == "1" else queryset


class ChatMessageInline(admin.TabularInline):
    """Raw message editor for moderation. Not attached by default: the thread view is the daily tool."""
    model = ChatMessage
    extra = 1
    fields = ("sender", "body", "created_at")
    readonly_fields = ("created_at",)
    ordering = ("created_at",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        recent_ids = qs.order_by("-created_at").values_list("id", flat=True)[:50]
        return qs.filter(id__in=recent_ids)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("email", "name", "unread_badge", "message_count", "last_message_display")
    list_filter = (UnreadFilter, ("last_message_at", admin.DateFieldListFilter))
    search_fields = ("email", "name", "messages__body")
    search_help_text = "Search by email, name or anything said in the chat"
    ordering = ("-last_message_at",)
    list_per_page = 25
    change_form_template = "admin/core/conversation/change_form.html"
    fields = ("email", "name")

    def get_queryset(self, request):
        """Unread and total counts are computed in the database in one pass."""
        unread = Count(
            "messages",
            filter=Q(messages__sender="guest") & (
                Q(admin_read_at__isnull=True) | Q(messages__created_at__gt=F("admin_read_at"))),
            distinct=True)
        return super().get_queryset(request).annotate(
            unread_n=unread, total_n=Count("messages", distinct=True))

    # ---- columns ------------------------------------------------------------
    @admin.display(description="", ordering="unread_n")
    def unread_badge(self, obj):
        if not obj.unread_n:
            return ""
        return pill(f"{obj.unread_n} new", RED)

    @admin.display(description="Messages", ordering="total_n")
    def message_count(self, obj):
        return obj.total_n

    @admin.display(description="Last activity", ordering="last_message_at")
    def last_message_display(self, obj):
        return obj.last_message_at.strftime("%d %b %Y, %H:%M")

    # ---- live thread --------------------------------------------------------
    def get_urls(self):
        custom = [
            path("<int:conversation_id>/send-reply/",
                 self.admin_site.admin_view(self.send_reply),
                 name="public_site_conversation_send_reply"),
        ]
        return custom + super().get_urls()

    def change_view(self, request, object_id, form_url="", extra_context=None):
        conversation = self.get_object(request, object_id)

        # Opening the page marks the thread read. GET only, so the POST that
        # follows a form save does not fire it again.
        if conversation and request.method == "GET":
            conversation.admin_read_at = timezone.now()
            conversation.save(update_fields=["admin_read_at"])

        extra_context = extra_context or {}
        extra_context["conversation"] = conversation
        extra_context["chat_messages"] = (
            conversation.messages.order_by("created_at") if conversation else [])
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def send_reply(self, request, conversation_id):
        """JSON endpoint behind the reply box. Saving the message triggers the guest email signal."""
        if request.method != "POST":
            return JsonResponse({"error": "POST required"}, status=405)
        if not self.has_change_permission(request):
            return JsonResponse({"error": "Permission denied"}, status=403)

        conversation = self.get_object(request, conversation_id)
        if not conversation:
            return JsonResponse({"error": "Conversation not found"}, status=404)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid request"}, status=400)

        body = data.get("body", "").strip()
        if not body:
            return JsonResponse({"error": "Message cannot be empty"}, status=400)

        msg = ChatMessage.objects.create(conversation=conversation, sender="staff", body=body)

        # Replying obviously means they have seen it too.
        conversation.admin_read_at = timezone.now()
        conversation.save(update_fields=["admin_read_at"])

        return JsonResponse({
            "success": True,
            "message": {
                "sender": msg.sender,
                "body": msg.body,
                "created_at": msg.created_at.strftime("%b %d, %H:%M"),
            },
        })


# =============================================================================
#  3. NEWSLETTER
# =============================================================================
class CampaignForm(forms.Form):
    subject = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "vTextField",
            "placeholder": "e.g. A note on our new Family Law desk",
        }))
    message = forms.CharField(
        widget=forms.Textarea(attrs={
            "rows": 12,
            "class": "vLargeTextField",
            "placeholder": "Plain text. Leave a blank line between paragraphs.",
        }))


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "status_col", "subscribed_at", "unsubscribed_at")
    list_filter = ("is_active", ("subscribed_at", admin.DateFieldListFilter))
    search_fields = ("email",)
    date_hierarchy = "subscribed_at"
    list_per_page = 50
    actions = ["deactivate", "reactivate", "export_csv"]
    change_list_template = "admin/core/newslettersubscriber/change_list.html"

    @admin.display(description="Status", ordering="is_active")
    def status_col(self, obj):
        return pill("Subscribed", DOC_PILL["confirmed"]) if obj.is_active else pill("Unsubscribed", CASE_PILL["closed"])

    # ---- campaign composer --------------------------------------------------
    def get_urls(self):
        return [
            path("send-campaign/", self.admin_site.admin_view(self.send_campaign),
                 name="newsletter_send_campaign"),
        ] + super().get_urls()

    def send_campaign(self, request):
        """Compose once, deliver individually (each email carries its own unsubscribe link)."""
        active = NewsletterSubscriber.objects.filter(is_active=True)
        if not active.exists():
            messages.warning(request, "There are no active subscribers to send to.")
            return redirect("admin:core_newslettersubscriber_changelist")

        if request.method == "POST":
            form = CampaignForm(request.POST)
            if form.is_valid():
                subject = form.cleaned_data["subject"]
                body = form.cleaned_data["message"]
                connection = get_newsletter_connection()
                connection.open()
                sent = failed = 0

                try:
                    for subscriber in active:
                        token = make_unsubscribe_token(subscriber.id)
                        unsubscribe_url = request.build_absolute_uri(
                            reverse("core:newsletter_unsubscribe", args=[token]))
                        html_content = render_to_string("emails/newsletter_campaign.html", {
                            "subject": subject,
                            "message": body,
                            "unsubscribe_url": unsubscribe_url,
                            "site_url": request.build_absolute_uri("/"),
                            "logo_url": request.build_absolute_uri(
                                settings.STATIC_URL + "images/static_images/logo-on-teal.png"),
                            "footer_image_url": request.build_absolute_uri(
                                settings.STATIC_URL + "images/lady-justice.jpg"),
                        })
                        email = EmailMultiAlternatives(
                            subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL,
                            to=[subscriber.email], connection=connection)
                        email.attach_alternative(html_content, "text/html")
                        try:
                            email.send()
                            sent += 1
                        except Exception:
                            failed += 1  # one bad address must not stop the campaign
                finally:
                    connection.close()

                NewsletterCampaign.objects.create(subject=subject, message=body, recipient_count=sent)
                messages.success(request, f"Campaign sent to {sent} subscriber(s).")
                if failed:
                    messages.warning(request, f"{failed} email(s) could not be delivered.")
                return redirect("admin:core_newslettersubscriber_changelist")
        else:
            form = CampaignForm()

        context = dict(
            self.admin_site.each_context(request),
            form=form,
            subscriber_count=active.count(),
            title="Send Newsletter Campaign",
            opts=self.model._meta,
        )
        return render(request, "admin/core/newslettersubscriber/send_campaign.html", context)

    # ---- bulk actions -------------------------------------------------------
    @admin.action(description="Unsubscribe selected", permissions=["change"])
    def deactivate(self, request, queryset):
        n = queryset.filter(is_active=True).update(is_active=False, unsubscribed_at=timezone.now())
        self.message_user(request, f"{n} subscriber(s) unsubscribed.", messages.SUCCESS)

    @admin.action(description="Reactivate selected", permissions=["change"])
    def reactivate(self, request, queryset):
        n = queryset.filter(is_active=False).update(is_active=True, unsubscribed_at=None)
        self.message_user(request, f"{n} subscriber(s) reactivated.", messages.SUCCESS)

    @admin.action(description="Export selected to CSV")
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="subscribers.csv"'
        response.write("\ufeff")  # lets Excel read UTF-8 correctly
        writer = csv.writer(response)
        writer.writerow(["Email", "Status", "Subscribed", "Unsubscribed"])
        for s in queryset:
            writer.writerow([s.email, "Subscribed" if s.is_active else "Unsubscribed",
                             s.subscribed_at.date(), s.unsubscribed_at.date() if s.unsubscribed_at else ""])
        return response


@admin.register(NewsletterCampaign)
class NewsletterCampaignAdmin(admin.ModelAdmin):
    """A permanent record of what was sent and to how many. Campaigns are only created by sending one."""
    list_display = ("subject", "preview", "sent_at", "recipient_count")
    date_hierarchy = "sent_at"
    readonly_fields = ("subject", "message", "sent_at", "recipient_count")

    @admin.display(description="Message")
    def preview(self, obj):
        text = " ".join(obj.message.split())
        return text[:90] + ("..." if len(text) > 90 else "")

    def has_add_permission(self, request):
        return False


# =============================================================================
#  4. WEBSITE CONTENT
# =============================================================================

# ---- Practice areas ---------------------------------------------------------
@admin.register(PracticeArea)
class PracticeAreaAdmin(admin.ModelAdmin):
    """Homepage grid. Reorder by editing the number inline; untick Active to hide without deleting."""
    list_display = ("title", "icon_col", "order", "is_active")
    list_editable = ("order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title", "description")
    ordering = ("order", "title")
    fieldsets = (
        (None, {"fields": ("title", "description")}),
        ("Presentation", {"fields": ("icon_class", ("order", "is_active"))}),
    )

    @admin.display(description="Icon class")
    def icon_col(self, obj):
        return format_html('<code style="font-size:.75rem;color:{}">{}</code>', TEAL, obj.icon_class)


# ---- Articles ---------------------------------------------------------------
from django.contrib import admin
from django.utils import timezone

from .models import Article, ArticleImage, ArticleTopic


class ArticleImageInline(admin.TabularInline):
    model = ArticleImage
    extra = 1
    fields = ("image", "caption", "order")
    ordering = ("order", "id")


@admin.register(ArticleTopic)
class ArticleTopicAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "published_at", "reading_time", "author_name")
    list_filter = ("status", "topics", "published_at")
    search_fields = ("title", "headline", "excerpt", "body")
    prepopulated_fields = {"slug": ("title",)}
    filter_horizontal = ("topics",)
    readonly_fields = ("reading_time", "created_at", "updated_at")
    date_hierarchy = "published_at"
    inlines = [ArticleImageInline]
    actions = ["publish_selected", "unpublish_selected"]
    fieldsets = (
        ("Card and URL", {"fields": ("title", "slug", "excerpt", "topics")}),
        ("Article", {"fields": ("headline", "subheadline", "author_name", "body")}),
        ("Publishing", {"fields": ("status", "published_at", "reading_time", "created_at", "updated_at")}),
    )

    @admin.action(description="Publish selected articles")
    def publish_selected(self, request, queryset):
        for article in queryset:
            article.status = "published"
            article.save()  # save() sets published_at when it is empty
        self.message_user(request, f"{queryset.count()} article(s) published.")

    @admin.action(description="Move selected articles back to draft")
    def unpublish_selected(self, request, queryset):
        queryset.update(status="draft", updated_at=timezone.now())
        self.message_user(request, f"{queryset.count()} article(s) moved to draft.")

# ---- Reviews ----------------------------------------------------------------
@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    """Client testimonials. Read-only by design: the firm can remove spam but never rewrite a client's words."""
    list_display = ("name", "stars", "excerpt", "ip_address", "created_at")
    list_filter = ("rating", ("created_at", admin.DateFieldListFilter))
    search_fields = ("name", "message", "ip_address")
    date_hierarchy = "created_at"
    list_per_page = 25
    fields = ("name", "rating", "message", "ip_address", "created_at")
    readonly_fields = fields

    @admin.display(description="Rating", ordering="rating")
    def stars(self, obj):
        return format_html(
            '<span style="color:{};letter-spacing:2px;font-size:1rem">{}{}</span>',
            ORANGE, "\u2605" * obj.rating, "\u2606" * (5 - obj.rating))

    @admin.display(description="Review")
    def excerpt(self, obj):
        return obj.message[:80] + ("..." if len(obj.message) > 80 else "")

    def has_add_permission(self, request):
        return False
  
@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ("thumb", "name", "role", "is_leadership", "is_active", "order")
    list_display_links = ("thumb", "name")
    list_editable = ("is_leadership", "is_active", "order")
    list_filter = ("is_leadership", "is_active")
    search_fields = ("name", "role", "bio")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("thumb_large",)
    fieldsets = (
        ("Identity", {"fields": ("name", "slug", "role")}),
        ("Photo", {"fields": ("photo", "thumb_large", "photo_focus")}),
        ("Profile", {"fields": ("bio", "credentials")}),
        ("Contact (optional)", {"fields": ("email", "linkedin_url")}),
        ("Display", {"fields": ("is_leadership", "is_active", "order")}),
    )

    @admin.display(description="Photo")
    def thumb(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" style="height:44px;width:44px;object-fit:cover;border-radius:50%;">',
                obj.photo.url,
            )
        return "-"

    @admin.display(description="Preview")
    def thumb_large(self, obj):
        if obj.photo:
            return format_html('<img src="{}" style="max-height:200px;border-radius:4px;">', obj.photo.url)
        return "No photo uploaded yet"