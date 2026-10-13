from django.db import models

from lawfirmsite import settings
import random
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from datetime import timedelta
import os
import uuid

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.core.mail import EmailMultiAlternatives

from django.utils.text import slugify
import re

from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import Truncator, slugify

from io import BytesIO
from PIL import Image as PILImage
from django.core.files.base import ContentFile
from django.db import models

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


@receiver(post_save, sender=ChatMessage)
def notify_guest_on_staff_reply(sender, instance, created, **kwargs):
    if not created or instance.sender != 'staff':
        return
 
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

    debounce_key = f'admin_notify_{instance.conversation_id}'
    if cache.get(debounce_key):
        return  # notified recently — admin panel badge still catches this message either way

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

    cache.set(debounce_key, True, timeout=300)  # 5-minute quiet window per conversation


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
    

class Review(models.Model):
    RATING_CHOICES = [(i, str(i)) for i in range(1, 6)]

    name = models.CharField(max_length=100)
    message = models.TextField(max_length=600)
    rating = models.PositiveSmallIntegerField(choices=RATING_CHOICES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    edit_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} - {self.rating} stars"

    @property
    def initials(self):
        parts = [p for p in self.name.strip().split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][0].upper()
        return (parts[0][0] + parts[-1][0]).upper()

    @property
    def is_editable(self):
        return (timezone.now() - self.created_at).total_seconds() <= 60
    

# Uses your existing User model (django.contrib.auth.models.User) as the login account.

class ClientProfile(models.Model):
    """Links a Django User to a portal client. Admin creates the User (name as
    username, e.g. 'john.mwangi') and this profile from the admin panel."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="client_profile")
    id_no = models.CharField("National ID number", max_length=20)
    phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class Case(models.Model):
    STATUS_CHOICES = [("open", "Open"), ("closed", "Closed"), ("on_hold", "On hold")]

    client = models.ForeignKey(ClientProfile, on_delete=models.CASCADE, related_name="cases")
    case_number = models.CharField(max_length=30, unique=True, help_text="Used by the client to log in.")
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="cases_created")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.case_number} — {self.title}"


def case_document_path(instance, filename):
    return f"case_documents/{instance.case.case_number}/{filename}"


class CaseDocument(models.Model):
    STATUS_CHOICES = [("pending", "Pending review"), ("confirmed", "Confirmed"), ("rejected", "Rejected")]

    ALLOWED_EXTENSIONS = {
        ".pdf": "pdf", ".doc": "word", ".docx": "word",
        ".jpg": "image", ".jpeg": "image", ".png": "image",
        ".mp4": "video", ".mov": "video",
    }

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="documents")
    file = models.FileField(upload_to=case_document_path)
    original_filename = models.CharField(max_length=255, blank=True)
    file_type = models.CharField(max_length=20, blank=True)  # pdf / word / image / video
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="documents_uploaded")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    admin_note = models.TextField(blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents_confirmed")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    # A confirmed document is locked. A client re-upload creates a NEW row that
    # points back here, preserving the confirmed original for the case record.
    supersedes = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="superseded_by_set")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def save(self, *args, **kwargs):
        if self.file and not self.original_filename:
            self.original_filename = os.path.basename(self.file.name)
        if self.file:
            ext = os.path.splitext(self.file.name)[1].lower()
            self.file_type = self.ALLOWED_EXTENSIONS.get(ext, "other")
        super().save(*args, **kwargs)

    def is_locked(self):
        return self.status == "confirmed"

    def __str__(self):
        return f"{self.original_filename} ({self.case.case_number})"


class DocumentRequest(models.Model):
    STATUS_CHOICES = [("pending", "Pending"), ("fulfilled", "Fulfilled")]

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="document_requests")
    description = models.CharField(max_length=255, help_text="What you're asking the client to provide.")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="document_requests_made")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    fulfilled_document = models.ForeignKey(CaseDocument, on_delete=models.SET_NULL, null=True, blank=True, related_name="fulfills_request")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.description} ({self.case.case_number})"


class ActivityLog(models.Model):
    ACTOR_ROLE_CHOICES = [("client", "Client"), ("admin", "Admin"), ("system", "System")]
    ACTION_CHOICES = [
        ("uploaded", "Uploaded document"), ("deleted", "Deleted document"),
        ("confirmed", "Confirmed document"), ("rejected", "Rejected document"),
        ("requested", "Requested document"), ("commented", "Added note"),
        ("logged_in", "Logged in"),
    ]

    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="activity_log")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    actor_role = models.CharField(max_length=10, choices=ACTOR_ROLE_CHOICES)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    description = models.CharField(max_length=255, blank=True)
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"[{self.case.case_number}] {self.get_action_display()}"
    
WORDS_PER_MINUTE = 200


def unique_slug(model, value, instance_pk=None, max_length=200, fallback="item"):
    """Slugify `value` and add -2, -3, ... until it is unique for `model`."""
    base = slugify(value)[:max_length] or fallback
    slug, counter = base, 1
    while model.objects.filter(slug=slug).exclude(pk=instance_pk).exists():
        counter += 1
        suffix = f"-{counter}"
        slug = f"{base[:max_length - len(suffix)]}{suffix}"
    return slug

class ArticleTopic(models.Model):
    """Medium-style topic (e.g. Commercial Law, Litigation). Used for chips, tabs and filtering."""

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=70, unique=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(ArticleTopic, self.name, self.pk, 70, "topic")
        super().save(*args, **kwargs)

class ArticleQuerySet(models.QuerySet):
    def published(self):
        """Live articles only. A future published_at schedules the article."""
        return self.filter(status="published", published_at__lte=timezone.now())

    def for_feed(self):
        """Everything a feed row needs in 3 queries total (no N+1), without loading the long body."""
        return self.published().defer("body").prefetch_related("images", "topics")

class Article(models.Model):
    STATUS_CHOICES = [("draft", "Draft"), ("published", "Published")]

    title = models.CharField(max_length=200, help_text="Shown in feeds and search, and used for the URL.")
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    headline = models.CharField(max_length=200, help_text="The big, bold headline at the top of the article.")
    subheadline = models.CharField(max_length=200, blank=True, help_text="Smaller line shown under the headline.")
    excerpt = models.CharField(
        max_length=300, blank=True,
        help_text="Short summary shown in feeds. Leave blank to use the start of the article.",
    )
    author_name = models.CharField(max_length=150, blank=True, help_text="Leave blank to use the firm name.")
    topics = models.ManyToManyField(ArticleTopic, related_name="articles", blank=True)
    body = models.TextField(help_text="Separate paragraphs with a blank line.")
    reading_time = models.PositiveSmallIntegerField(default=1, editable=False, help_text="Minutes, calculated automatically.")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="draft", db_index=True)
    published_at = models.DateTimeField(null=True, blank=True, help_text="Set a future date to schedule the article.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ArticleQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at", "-created_at"]
        indexes = [models.Index(fields=["status", "-published_at"])]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("core:article_detail", args=[self.slug])

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(Article, self.title, self.pk, 200, "article")
        if self.status == "published" and not self.published_at:
            self.published_at = timezone.now()

        body = (self.body or "").strip()
        self.reading_time = max(1, round(len(body.split()) / WORDS_PER_MINUTE))
        if not self.excerpt and body:
            first = re.split(r"\n\s*\n", body.replace("\r\n", "\n"), maxsplit=1)[0]
            self.excerpt = Truncator(" ".join(first.split())).chars(280)
        super().save(*args, **kwargs)

    @property
    def is_live(self):
        return self.status == "published" and self.published_at is not None and self.published_at <= timezone.now()

    @property
    def display_author(self):
        return self.author_name or "Ngima Wangai & Company Advocates"

    @property
    def cover_image(self):
        # Iterate .all() (not .first()) so a prefetch_related("images") cache is used.
        for img in self.images.all():
            return img.image
        return None

class ArticleImage(models.Model):
    article = models.ForeignKey("Article", related_name="images", on_delete=models.CASCADE)
    image = models.ImageField(upload_to="articles/%Y/%m/")
    caption = models.CharField(max_length=200, blank=True)
    order = models.PositiveIntegerField(default=0)
    
    # Store dimensions to prevent layout shifts (CLS)
    width = models.PositiveIntegerField(editable=False, null=True)
    height = models.PositiveIntegerField(editable=False, null=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"Image for {self.article.headline}"

    def save(self, *args, **kwargs):
        if self.image:
            try:
                img = PILImage.open(self.image)
                
                # Capture original dimensions
                self.width, self.height = img.size

                # Convert RGBA/Palette modes to RGB for JPEG/WebP compression compatibility
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")

                # Resize large images down to max 1600px width to save bandwidth & prevent ragging/lagging
                max_size = (1600, 1600)
                img.thumbnail(max_size, PILImage.Resampling.LANCZOS)

                # Compress and save to buffer
                buffer = BytesIO()
                img.save(buffer, format="JPEG", quality=85, optimize=True)
                buffer.seek(0)

                # Replace original file with compressed content
                file_name = self.image.name.rsplit(".", 1)[0] + ".jpg"
                self.image.save(file_name, ContentFile(buffer.read()), save=False)
                
                # Re-fetch updated dimensions after compression resize
                self.width, self.height = img.size
            except Exception:
                pass  # Fallback gracefully if image processing fails

        super().save(*args, **kwargs)
 
import re
class TeamMember(models.Model):
    FOCUS_CENTER = "center"
    FOCUS_TOP = "top"
    FOCUS_CHOICES = [
        (FOCUS_CENTER, "Center"),
        (FOCUS_TOP, "Top (keeps heads in frame on wide crops)"),
    ]

    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, unique=True)
    role = models.CharField(max_length=150, help_text="e.g. Managing Partner, Senior Associate")
    bio = models.TextField(blank=True, help_text="Separate paragraphs with a blank line.")
    credentials = models.CharField(
        max_length=400, blank=True,
        help_text="Separate items with a pipe: LLB, University of Nairobi | Law Society of Kenya",
    )
    photo = models.ImageField(
        upload_to="team/", blank=True,
        help_text="Portrait, at least 1200px wide. Initials are shown if left empty.",
    )
    photo_focus = models.CharField(max_length=10, choices=FOCUS_CHOICES, default=FOCUS_CENTER)
    email = models.EmailField(blank=True, help_text="Shows an email icon on the photo when filled.")
    linkedin_url = models.URLField(blank=True, help_text="Shows a LinkedIn icon on the photo when filled.")
    is_leadership = models.BooleanField(
        default=False, help_text="Show in the Leadership section (homepage and team page)."
    )
    is_active = models.BooleanField(default=True, help_text="Untick to hide without deleting.")
    order = models.PositiveSmallIntegerField(default=0, help_text="Lower numbers appear first.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "Team Member"
        verbose_name_plural = "Team Members"

    def __str__(self):
        return self.name

    @property
    def bio_paragraphs(self):
        return [p.strip() for p in re.split(r"\n\s*\n", self.bio.strip()) if p.strip()]

    @property
    def credential_list(self):
        return [c.strip() for c in self.credentials.split("|") if c.strip()]

    @property
    def initials(self):
        parts = self.name.split()
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()

# ---------------------------------------------------------------------------
# Process section (homepage)
# ---------------------------------------------------------------------------

PROCESS_CACHE_KEY = "process:section:v1"


class ProcessSection(models.Model):
    """The words of the 'Our Process' section. There is only ever one. Design lives in the template."""

    is_published = models.BooleanField(default=True, help_text="Untick to hide the section on the website.")
    eyebrow = models.CharField(max_length=60, blank=True, default="Our Process", help_text="Small label above the heading.")
    heading = models.CharField(max_length=120, default="How We Serve Our Clients")
    intro = models.TextField(blank=True, help_text="Short paragraph next to the heading.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Process section"
        verbose_name_plural = "Process section"

    def __str__(self):
        return "Our Process section"

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        super().save(*args, **kwargs)


class ProcessStep(models.Model):
    section = models.ForeignKey(ProcessSection, related_name="steps", on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    description = models.TextField(help_text="One to three sentences works best.")
    order = models.PositiveIntegerField(default=0, help_text="Lower numbers appear first. Steps are numbered automatically.")
    is_active = models.BooleanField(default=True, help_text="Untick to hide this step without deleting it.")

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title


@receiver([post_save, post_delete], sender=ProcessSection)
@receiver([post_save, post_delete], sender=ProcessStep)
def _clear_process_cache(sender, **kwargs):
    cache.delete(PROCESS_CACHE_KEY)