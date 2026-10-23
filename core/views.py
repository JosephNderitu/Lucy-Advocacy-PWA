import os
import json
import random
import re
import secrets
import uuid
from io import BytesIO
from django.http import JsonResponse, HttpResponse, Http404
from django.views.decorators.http import require_POST
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .models import *
from .newsletter_utils import read_unsubscribe_token

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.cache import cache

from .forms import *
from django.db.models import Avg, Count, Q

from datetime import timedelta
from django.core.paginator import Paginator
from django.template.loader import get_template, render_to_string
from xhtml2pdf import pisa

from .reviews_support import home_review_context, review_stats, serialize_review

DEVICE_COOKIE = "rv_device"
DEVICE_SALT = "rv-device"
DEVICE_COOKIE_AGE = 60 * 60 * 24 * 365 * 2
DEVICE_DAILY_LIMIT = 2      # reviews per device per rolling 24 hours
IP_DAILY_BACKSTOP = 20      # generous safety net so shared wifi still works


def _device_id(request):
    """Signed cookie first, then the id the browser kept in localStorage, else a brand new device."""
    raw = request.get_signed_cookie(DEVICE_COOKIE, default="", salt=DEVICE_SALT) or request.POST.get("device_id", "")
    try:
        return uuid.UUID(str(raw)).hex
    except (ValueError, AttributeError, TypeError):
        return uuid.uuid4().hex


def _remember_device(request, response, device_id):
    response.set_signed_cookie(
        DEVICE_COOKIE, device_id, salt=DEVICE_SALT, max_age=DEVICE_COOKIE_AGE,
        httponly=True, samesite="Lax", secure=request.is_secure(),
    )
    return response

def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")

def home(request):
    practice_areas = list(
        PracticeArea.objects.filter(is_active=True).values("id", "title", "description", "icon_class")
    )
    latest_articles = Article.objects.filter(status="published")[:4]
 
    return render(request, "core/home.html", {
        "practice_areas": practice_areas,
        "latest_articles": latest_articles,
        **home_review_context(),   # adds "reviews" and "review_stats" (cached)
    })

def team(request):
       return redirect(reverse('core:about') + '#team', permanent=True)
    
def _token_ok(review, request):
    return secrets.compare_digest(str(review.edit_token), request.POST.get("token", ""))
 
@require_POST
def submit_review(request):
    ip = get_client_ip(request)
    device_id = _device_id(request)
    since = timezone.now() - timedelta(hours=24)

    too_many = {
        "status": "error",
        "message": "You have reached the limit of 2 reviews per day on this device. Please try again tomorrow.",
    }
    if Review.objects.filter(device_id=device_id, created_at__gte=since).count() >= DEVICE_DAILY_LIMIT:
        return _remember_device(request, JsonResponse(too_many, status=429), device_id)
    if ip and Review.objects.filter(ip_address=ip, created_at__gte=since).count() >= IP_DAILY_BACKSTOP:
        return _remember_device(request, JsonResponse(too_many, status=429), device_id)
 
    form = ReviewForm(request.POST)
    if form.is_valid():
        review = form.save(commit=False)
        review.ip_address = ip
        review.device_id = device_id
        review.save()
        stats = review_stats()
        return _remember_device(request, JsonResponse({
            "status": "success",
            "message": "Thank you for sharing your experience.",
            "stats": stats,
            "new_avg": stats["avg"],      # kept for older scripts
            "new_total": stats["total"],
            "review": serialize_review(review, include_private=True),
        }), device_id)
    return JsonResponse({
        "status": "error",
        "message": "Please fill in your name, a star rating, and your review.",
    }, status=400)
 
@require_POST
def update_review(request, review_id):
    review = Review.objects.filter(pk=review_id).first()
    if review is None:
        return JsonResponse({"status": "error", "message": "Review not found."}, status=404)
    if not _token_ok(review, request):
        return JsonResponse({"status": "error", "message": "You are not allowed to edit this review."}, status=403)
    if not review.is_editable:
        return JsonResponse({"status": "error", "message": "The one minute edit window has closed."}, status=403)
 
    form = ReviewForm(request.POST, instance=review)
    if form.is_valid():
        form.save()
        stats = review_stats()
        return JsonResponse({
            "status": "success",
            "message": "Your review has been updated.",
            "stats": stats,
            "new_avg": stats["avg"],
            "review": serialize_review(review, include_private=True),
        })
    return JsonResponse({"status": "error", "message": "Please check your review and try again."}, status=400)
 
@require_POST
def delete_review(request, review_id):
    review = Review.objects.filter(pk=review_id).first()
    if review is None:
        return JsonResponse({"status": "error", "message": "Review not found."}, status=404)
    if not _token_ok(review, request):
        return JsonResponse({"status": "error", "message": "You are not allowed to delete this review."}, status=403)
    if not review.is_editable:
        return JsonResponse({"status": "error", "message": "The one minute window to delete this review has closed."}, status=403)
 
    review.delete()
    stats = review_stats()
    return JsonResponse({
        "status": "success",
        "message": "Your review has been deleted.",
        "stats": stats,
        "new_avg": stats["avg"],
        "new_total": stats["total"],
    })

def about(request):
    practice_area_count = PracticeArea.objects.filter(is_active=True).count()
    members = TeamMember.objects.filter(is_active=True)

    faqs = [
        {
            "question": "How do I book a consultation?",
            "answer": "Reach us through the contact page, by phone, or by email. We'll ask a few "
                      "questions about your matter and schedule a consultation with the right advocate.",
        },
        {
            "question": "What areas of law does the firm handle?",
            "answer": "We're a full-service commercial and corporate practice covering banking & "
                      "financial institutions, alternative dispute resolution, immigration, conveyancing "
                      "& real estate, insurance, legal audit & training, probate & estate planning, and "
                      "family law. See our Practice Areas section on the homepage for details on each.",
        },
        {
            "question": "How quickly will I hear back after reaching out?",
            "answer": "We prioritize responsiveness. Inquiries are typically acknowledged within one "
                      "business day, and we'll give you a clear timeline for next steps from there.",
        },
        {
            "question": "Do you represent clients outside Nairobi?",
            "answer": "Yes. We handle matters across Kenya's court system, including the High Court, "
                      "Court of Appeal, and Supreme Court, and advise on cross-border and international "
                      "matters through our immigration and private international law practice.",
        },
        {
            "question": "Are your advocates registered with the Law Society of Kenya?",
            "answer": "Yes, all our advocates are LSK members in good standing, and our managing "
                      "partner is also a certified professional mediator.",
        },
        {
            "question": "Can you help with both litigation and out-of-court resolution?",
            "answer": "Both. We handle matters through negotiation, mediation, arbitration, and full "
                      "litigation, and we'll recommend the approach that best protects your interests "
                      "and, where possible, your business relationships.",
        },
        {
            "question": "How are your fees structured?",
            "answer": "Fees depend on the nature and complexity of the matter. We'll discuss scope "
                      "and cost transparently during your initial consultation before any engagement begins.",
        },
        {
            "question": "Do you work with companies as well as individuals?",
            "answer": "Yes. Alongside individual clients, we advise banks, co-operative societies, "
                      "and limited companies on compliance, legal audits, employment law, and corporate "
                      "governance.",
        },
    ]

    return render(request, "core/about.html", {
        "practice_area_count": practice_area_count,
        "faqs": faqs,
        'leadership': members.filter(is_leadership=True),
        'team_members': members.filter(is_leadership=False),
    })

MESSAGES_PAGE_SIZE = 30
def contact(request):
    session_email = request.session.get('contact_email')
    conversation = None
    messages = []
    has_more = False
    if session_email:
        conversation = Conversation.objects.filter(email=session_email).first()
        if conversation:
            recent = list(conversation.messages.order_by('-created_at')[:MESSAGES_PAGE_SIZE]
                           .values('id', 'sender', 'body', 'created_at'))
            messages = list(reversed(recent))
            has_more = conversation.messages.count() > MESSAGES_PAGE_SIZE

    return render(request, 'core/contact.html', {
        'session_email': session_email,
        'messages': messages,
        'has_more': has_more,
    })

def privacy_policy(request):
    return render(request, "core/privacy_policy.html")
 
def terms_conditions(request):
    return render(request, "core/terms_conditions.html")
 
def cookie_policy(request):
    return render(request, "core/cookie_policy.html")

@require_POST
def send_verification_code(request):
    data = json.loads(request.body)
    email = data.get('email', '').strip().lower()
    if not email or '@' not in email:
        return JsonResponse({'error': 'Please enter a valid email address.'}, status=400)

    cooldown_key = f'verify_cooldown_{email}'
    if cache.get(cooldown_key):
        return JsonResponse(
            {'error': 'Please wait a moment before requesting another code.'},
            status=429,
        )

    code = str(random.randint(100000, 999999))
    EmailVerification.objects.create(email=email, code=code)

    send_mail(
        subject="Your Ngima Wangai & Company Advocates verification code",
        message=(
            f"Your verification code is: {code}\n\n"
            f"This code expires in 10 minutes.\n\n"
            f"Ngima Wangai & Company Advocates"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )

    cache.set(cooldown_key, True, timeout=60)
    return JsonResponse({'success': True})

@require_POST
def verify_code(request):
    data = json.loads(request.body)
    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()
    name = data.get('name', '').strip()

    attempts_key = f'verify_attempts_{email}'
    attempts = cache.get(attempts_key, 0)
    if attempts >= 5:
        return JsonResponse(
            {'error': 'Too many incorrect attempts. Please request a new code.'},
            status=429,
        )

    verification = EmailVerification.objects.filter(
        email=email, code=code, is_used=False
    ).order_by('-created_at').first()

    if not verification:
        cache.set(attempts_key, attempts + 1, timeout=600)
        return JsonResponse({'error': 'Invalid code.'}, status=400)

    if verification.is_expired():
        cache.set(attempts_key, attempts + 1, timeout=600)
        return JsonResponse({'error': 'That code has expired. Request a new one.'}, status=400)

    cache.delete(attempts_key)

    verification.is_used = True
    verification.save(update_fields=['is_used'])

    conversation, created = Conversation.objects.get_or_create(email=email)
    if name and not conversation.name:
        conversation.name = name
        conversation.save(update_fields=['name'])

    request.session['contact_email'] = email
    request.session.set_expiry(60 * 60 * 24 * 30)

    messages = list(conversation.messages.values('id', 'sender', 'body', 'created_at'))
    return JsonResponse({'success': True, 'messages': messages})

def get_messages(request):
    """Two modes, chosen by which query param is present:
    - ?before=<id>  — older history, for the "Load earlier messages" button.
    - ?after=<id>   — new messages since the client's last-seen id. This is
      the one the polling loop calls every few seconds.
    Neither should be sent in the same request; before wins if both are.
    """
    email = request.session.get('contact_email')
    if not email:
        return JsonResponse({'error': 'Not verified.'}, status=401)

    conversation = Conversation.objects.filter(email=email).first()
    if not conversation:
        return JsonResponse({'messages': [], 'has_more': False})

    before = request.GET.get('before')
    after = request.GET.get('after')

    if before:
        qs = conversation.messages.filter(created_at__lt=before).order_by('-created_at')
        page = list(qs[:MESSAGES_PAGE_SIZE].values('id', 'sender', 'body', 'created_at'))
        has_more = qs.count() > MESSAGES_PAGE_SIZE
        return JsonResponse({'messages': list(reversed(page)), 'has_more': has_more})

    if after:
        qs = conversation.messages.filter(id__gt=after).order_by('created_at')[:100]
        return JsonResponse({'messages': list(qs.values('id', 'sender', 'body', 'created_at')), 'has_more': False})

    # Neither param — just the latest page, same as the initial page load.
    qs = conversation.messages.order_by('-created_at')
    page = list(qs[:MESSAGES_PAGE_SIZE].values('id', 'sender', 'body', 'created_at'))
    has_more = qs.count() > MESSAGES_PAGE_SIZE
    return JsonResponse({'messages': list(reversed(page)), 'has_more': has_more})

@require_POST
def send_message(request):
    email = request.session.get('contact_email')
    if not email:
        return JsonResponse({'error': 'Not verified.'}, status=401)

    data = json.loads(request.body)
    body = data.get('body', '').strip()
    if not body:
        return JsonResponse({'error': 'Message cannot be empty.'}, status=400)

    conversation, _ = Conversation.objects.get_or_create(email=email)
    msg = ChatMessage.objects.create(conversation=conversation, sender='guest', body=body)
    conversation.last_message_at = timezone.now()
    conversation.save(update_fields=['last_message_at'])

    # Returning the saved message lets the client render it immediately
    # instead of waiting for the next poll tick to see its own message.
    return JsonResponse({
        'success': True,
        'message': {
            'id': msg.id, 'sender': msg.sender, 'body': msg.body,
            'created_at': msg.created_at.isoformat(),
        },
    })
    
def contact_logout(request):
    request.session.pop('contact_email', None)
    return JsonResponse({'success': True})

@require_POST
def newsletter_subscribe(request):
    email = (request.POST.get("email") or "").strip().lower()

    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse(
            {"ok": False, "status": "invalid", "message": "Please enter a valid email address."},
            status=400,
        )

    subscriber, created = NewsletterSubscriber.objects.get_or_create(email=email)

    if created:
        return JsonResponse({
            "ok": True,
            "status": "subscribed",
            "message": "You're subscribed. Thank you for joining us.",
        })

    if subscriber.is_active:
        return JsonResponse({
            "ok": False,
            "status": "already_subscribed",
            "message": "This email is already on our list.",
        })

    # Was unsubscribed before, a fresh sign-up reactivates the same record.
    subscriber.is_active = True
    subscriber.unsubscribed_at = None
    subscriber.save(update_fields=["is_active", "unsubscribed_at"])
    return JsonResponse({
        "ok": True,
        "status": "resubscribed",
        "message": "Welcome back, you're subscribed again.",
    })

def newsletter_unsubscribe(request, token):
    try:
        subscriber_id = read_unsubscribe_token(token)
    except signing.SignatureExpired:
        return render(request, "core/newsletter_unsubscribe.html", {"error": "expired"})
    except signing.BadSignature:
        return render(request, "core/newsletter_unsubscribe.html", {"error": "invalid"})

    subscriber = get_object_or_404(NewsletterSubscriber, pk=subscriber_id)

    if subscriber.is_active:
        subscriber.is_active = False
        subscriber.unsubscribed_at = timezone.now()
        subscriber.save(update_fields=["is_active", "unsubscribed_at"])

    return render(request, "core/newsletter_unsubscribe.html", {"subscriber": subscriber})
# --- Append to core/views.py ---
LOGIN_ATTEMPT_LIMIT = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60

def _client_ip(request):
    return request.META.get("REMOTE_ADDR", "unknown")

def _get_client_case(request):
    """MVP assumption: one active case per client. Extend with a case-picker
    if a client will ever have more than one."""
    profile = getattr(request.user, "client_profile", None)
    if not profile:
        return None
    return profile.cases.order_by("-created_at").first()

def _log_activity(case, actor, actor_role, action, description=""):
    ActivityLog.objects.create(case=case, actor=actor, actor_role=actor_role, action=action, description=description)

def portal_login(request):
    if request.user.is_authenticated and hasattr(request.user, "client_profile"):
        return redirect("core:portal_dashboard")

    form = ClientLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        throttle_key = f"portal_login_attempts:{_client_ip(request)}"
        attempts = cache.get(throttle_key, 0)
        if attempts >= LOGIN_ATTEMPT_LIMIT:
            messages.error(request, "Too many failed attempts. Please try again in 15 minutes.")
            return render(request, "core/login.html", {"form": form})

        user = authenticate(
            request,
            case_number=form.cleaned_data["case_number"],
            id_no=form.cleaned_data["id_no"],
        )
        if user is not None:
            cache.delete(throttle_key)
            login(request, user)
            case = _get_client_case(request)
            if case:
                _log_activity(case, user, "client", "logged_in")
            return redirect("core:portal_dashboard")

        cache.set(throttle_key, attempts + 1, LOGIN_LOCKOUT_SECONDS)
        messages.error(request, "Case number and ID number did not match our records.")

    return render(request, "core/login.html", {"form": form})

def portal_logout(request):
    logout(request)
    return redirect("core:portal_login")

from collections import Counter
@login_required
def portal_dashboard(request):
    case = _get_client_case(request)
    if not case:
        messages.error(request, "No case is linked to your account yet. Contact the firm.")
        return redirect("core:portal_login")
 
    wants_json = request.headers.get("x-requested-with") == "XMLHttpRequest"
 
    # Handle the upload first. A successful POST redirects, so it never pays
    # for the read queries below.
    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.case = case
            doc.uploaded_by = request.user
            doc.save()
            _log_activity(case, request.user, "client", "uploaded", doc.original_filename)
            messages.success(request, "Document uploaded and pending review.")
            if wants_json:
                return JsonResponse({"ok": True})
            return redirect("core:portal_dashboard")
 
        if wants_json:
            errors = [e for errs in form.errors.values() for e in errs]
            return JsonResponse({"ok": False, "error": errors[0] if errors else "Upload failed."}, status=400)
        # Non-JS fallback: fall through and re-render the page with form errors.
    else:
        form = DocumentUploadForm()
 
    # Three small queries. Counts come from the list we already loaded, so the
    # four extra COUNT queries and the unused select_related join are gone.
    documents = list(case.documents.all())
    by_status = Counter(d.status for d in documents)
    doc_counts = {
        "total": len(documents),
        "pending": by_status["pending"],
        "confirmed": by_status["confirmed"],
        "rejected": by_status["rejected"],
    }
    pending_requests = list(case.document_requests.filter(status="pending").order_by("created_at"))
    recent_activity = list(case.activity_log.all()[:6])
 
    return render(request, "core/dashboard.html", {
        "case": case,
        "documents": documents,
        "pending_requests": pending_requests,
        "recent_activity": recent_activity,
        "form": form,
        "doc_counts": doc_counts,
    })

@login_required
def portal_document_delete(request, pk):
    case = _get_client_case(request)
    doc = get_object_or_404(CaseDocument, pk=pk, case=case)
    if doc.is_locked():
        messages.error(request, "This document is confirmed and can't be deleted. Upload a new version instead.")
    else:
        _log_activity(case, request.user, "client", "deleted", doc.original_filename)
        doc.file.delete(save=False)
        doc.delete()
        messages.success(request, "Document deleted.")
    return redirect("core:portal_dashboard")

@login_required
def portal_activity_log(request):
    case = _get_client_case(request)
    if not case:
        return redirect("core:portal_login")
    entries = case.activity_log.all()
    return render(request, "core/activity_log.html", {"case": case, "entries": entries})

def service_worker(request):
    """Serves static/sw.js at the true site root (/sw.js), not /static/sw.js.
    A service worker's scope defaults to the directory it's served from —
    serving it under /static/ would limit it to controlling only /static/*,
    not the whole site."""
    path = os.path.join(settings.BASE_DIR, 'static', 'sw.js')
    with open(path, 'r') as f:
        content = f.read()
    return HttpResponse(content, content_type='application/javascript')

# Move these into settings.py when convenient (FIRM_CONTACT_EMAIL / FIRM_CONTACT_PHONE).
FIRM_EMAIL = getattr(settings, "FIRM_CONTACT_EMAIL", "nwangailawadvocates@gmail.com")
FIRM_PHONE = getattr(settings, "FIRM_CONTACT_PHONE", "+254 714 535 492")

def paginate_article_body(body, words_per_page=550):
    """Split the body into 'pages' of paragraphs. Used for the PDF and for the gallery position on the web page."""
    # Browsers submit textarea line breaks as \r\n, so normalise before splitting on blank lines.
    text = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if p.strip()]
    pages, current_page, current_words = [], [], 0
    for para in paragraphs:
        word_count = len(para.split())
        if current_page and current_words + word_count > words_per_page:
            pages.append(current_page)
            current_page, current_words = [], 0
        current_page.append(para)
        current_words += word_count
    if current_page:
        pages.append(current_page)
    return pages or [[]]

def _live_topics():
    now = timezone.now()
    return (
        ArticleTopic.objects
        .annotate(n=Count("articles", filter=Q(articles__status="published", articles__published_at__lte=now)))
        .filter(n__gt=0)
    )

def article_list(request):
    q = request.GET.get("q", "").strip()[:100]
    topic_slug = request.GET.get("topic", "").strip()

    articles = Article.objects.for_feed()
    active_topic = None
    if topic_slug:
        active_topic = get_object_or_404(ArticleTopic, slug=topic_slug)
        articles = articles.filter(topics=active_topic)
    if q:
        articles = articles.filter(
            Q(title__icontains=q) | Q(headline__icontains=q) | Q(subheadline__icontains=q)
            | Q(excerpt__icontains=q) | Q(body__icontains=q)
        )

    page_obj = Paginator(articles, 10).get_page(request.GET.get("page"))

    # Keep search/topic in the pagination links
    params = request.GET.copy()
    params.pop("page", None)

    return render(request, "core/article_list.html", {
        "page_obj": page_obj,
        "topics": _live_topics(),
        "active_topic": active_topic,
        "q": q,
        "querystring": params.urlencode(),
        "contact_email": FIRM_EMAIL,
        "contact_phone": FIRM_PHONE,
    })

def _get_article_or_404(request, slug):
    article = get_object_or_404(Article.objects.prefetch_related("images", "topics"), slug=slug)
    is_preview = not article.is_live
    if is_preview and not request.user.is_staff:
        raise Http404
    return article, is_preview

def _related_articles(article, limit=3):
    topic_ids = [t.pk for t in article.topics.all()]
    base = Article.objects.for_feed().exclude(pk=article.pk)
    related = list(base.filter(topics__in=topic_ids).distinct()[:limit]) if topic_ids else []
    if len(related) < limit:  # top up with the newest articles
        have = [a.pk for a in related]
        related += list(base.exclude(pk__in=have)[: limit - len(related)])
    return related

def _article_context(request, article, is_preview):
    images = list(article.images.all())
    return {
        "article": article,
        "pages": paginate_article_body(article.body),
        "images": images,
        "is_preview": is_preview,
        "contact_email": FIRM_EMAIL,
        "contact_phone": FIRM_PHONE,
    }

def article_detail(request, slug):
    article, is_preview = _get_article_or_404(request, slug)
    context = _article_context(request, article, is_preview)
    context.update({
        "related_articles": _related_articles(article),
        # Optional: use these in base.html (<meta name="description">, og:image, og:title)
        "meta_description": article.excerpt,
        "og_image": request.build_absolute_uri(article.cover_image.url) if article.cover_image else "",
    })
    return render(request, "core/article_detail.html", context)

def _pdf_link_callback(uri, rel):
    """Let xhtml2pdf find /media/ and /static/ files on disk. Absolute file paths pass through untouched."""
    from django.contrib.staticfiles import finders

    if settings.MEDIA_URL and uri.startswith(settings.MEDIA_URL):
        return os.path.join(settings.MEDIA_ROOT, uri[len(settings.MEDIA_URL):])
    if settings.STATIC_URL and uri.startswith(settings.STATIC_URL):
        rel_path = uri[len(settings.STATIC_URL):]
        return finders.find(rel_path) or os.path.join(settings.STATIC_ROOT or "", rel_path)
    return uri

def _html_to_pdf(html, request):
    """Uses WeasyPrint if installed, otherwise xhtml2pdf. Install one of them: pip install weasyprint  OR  pip install xhtml2pdf"""
    try:
        from weasyprint import HTML
        return HTML(string=html, base_url=request.build_absolute_uri("/")).write_pdf()
    except ImportError:
        pass
    try:
        from xhtml2pdf import pisa
    except ImportError as exc:
        raise RuntimeError("Install WeasyPrint or xhtml2pdf to generate article PDFs.") from exc
    buffer = BytesIO()
    result = pisa.CreatePDF(src=html, dest=buffer, link_callback=_pdf_link_callback, encoding="utf-8")
    if result.err:
        raise RuntimeError("PDF generation failed.")
    return buffer.getvalue()

def article_pdf(request, slug):
    article, is_preview = _get_article_or_404(request, slug)
    html = render_to_string("core/article_pdf.html", _article_context(request, article, is_preview), request=request)
    response = HttpResponse(_html_to_pdf(html, request), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{article.slug}.pdf"'
    return response