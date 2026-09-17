import json
import random
from django.shortcuts import render

from .models import PracticeArea
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import Conversation, ChatMessage, EmailVerification
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
import os
from django.http import HttpResponse, Http404
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
from django.db.models import Avg

from datetime import timedelta
from django.core.paginator import Paginator
from django.template.loader import get_template
from xhtml2pdf import pisa


def get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def serialize_review(review, include_private=False):
    data = {
        "id": review.id,
        "name": review.name,
        "initials": review.initials,
        "message": review.message,
        "rating": review.rating,
        "created_at": review.created_at.strftime("%B %Y"),
    }
    if include_private:
        data["token"] = str(review.edit_token)
    return data


def home(request):
    practice_areas = list(
        PracticeArea.objects.filter(is_active=True).values(
            "id", "title", "description", "icon_class"
        )
    )
    review_qs = Review.objects.order_by("-created_at")[:30]
    reviews = [serialize_review(r) for r in review_qs]
    agg = Review.objects.aggregate(avg=Avg("rating"))
    review_avg = round(agg["avg"] or 0, 1)
    review_total = Review.objects.count()
    latest_articles = Article.objects.filter(status="published")[:4]

    return render(request, "core/home.html", {
        "practice_areas": practice_areas,
        "reviews": reviews,
        "review_avg": review_avg,
        "review_total": review_total,
        "latest_articles": latest_articles,
    })


@require_POST
def submit_review(request):
    ip = get_client_ip(request)
    one_week_ago = timezone.now() - timedelta(days=7)
    if ip and Review.objects.filter(ip_address=ip, created_at__gte=one_week_ago).exists():
        return JsonResponse({
            "status": "error",
            "message": "Only one review per week is allowed from your connection. Please check back soon.",
        }, status=429)

    form = ReviewForm(request.POST)
    if form.is_valid():
        review = form.save(commit=False)
        review.ip_address = ip
        review.save()
        new_avg = round(Review.objects.aggregate(avg=Avg("rating"))["avg"] or 0, 1)
        return JsonResponse({
            "status": "success",
            "message": "Thank you for sharing your experience.",
            "new_avg": new_avg,
            "new_total": Review.objects.count(),
            "review": serialize_review(review, include_private=True),
        })
    return JsonResponse({
        "status": "error",
        "message": "Please fill in your name, a star rating, and your review.",
    }, status=400)


@require_POST
def update_review(request, review_id):
    try:
        review = Review.objects.get(id=review_id)
    except Review.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Review not found."}, status=404)

    if str(review.edit_token) != request.POST.get("token", ""):
        return JsonResponse({"status": "error", "message": "You are not allowed to edit this review."}, status=403)

    if not review.is_editable:
        return JsonResponse({"status": "error", "message": "The one minute edit window has closed."}, status=403)

    form = ReviewForm(request.POST, instance=review)
    if form.is_valid():
        form.save()
        new_avg = round(Review.objects.aggregate(avg=Avg("rating"))["avg"] or 0, 1)
        return JsonResponse({
            "status": "success",
            "message": "Your review has been updated.",
            "new_avg": new_avg,
            "review": serialize_review(review, include_private=True),
        })
    return JsonResponse({"status": "error", "message": "Please check your review and try again."}, status=400)


@require_POST
def delete_review(request, review_id):
    try:
        review = Review.objects.get(id=review_id)
    except Review.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Review not found."}, status=404)

    if str(review.edit_token) != request.POST.get("token", ""):
        return JsonResponse({"status": "error", "message": "You are not allowed to delete this review."}, status=403)

    if not review.is_editable:
        return JsonResponse({"status": "error", "message": "The one minute window to delete this review has closed."}, status=403)

    review.delete()
    new_avg = round(Review.objects.aggregate(avg=Avg("rating"))["avg"] or 0, 1)
    return JsonResponse({
        "status": "success",
        "message": "Your review has been deleted.",
        "new_avg": new_avg,
        "new_total": Review.objects.count(),
    })

def about(request):
    practice_area_count = PracticeArea.objects.filter(is_active=True).count()

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

 
from django.core.cache import cache

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


@login_required
def portal_dashboard(request):
    case = _get_client_case(request)
    if not case:
        messages.error(request, "No case is linked to your account yet. Contact the firm.")
        return redirect("core:portal_login")

    documents = case.documents.select_related("confirmed_by")
    pending_requests = case.document_requests.filter(status="pending")
    recent_activity = case.activity_log.all()[:6]
    doc_counts = {
        "total": documents.count(),
        "pending": documents.filter(status="pending").count(),
        "confirmed": documents.filter(status="confirmed").count(),
        "rejected": documents.filter(status="rejected").count(),
    }

    if request.method == "POST":
        form = DocumentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.case = case
            doc.uploaded_by = request.user
            doc.save()
            _log_activity(case, request.user, "client", "uploaded", doc.original_filename)
            messages.success(request, "Document uploaded and pending review.")
            return redirect("core:portal_dashboard")
    else:
        form = DocumentUploadForm()

    return render(request, "core/dashboard.html", {
        "case": case, "documents": documents, "pending_requests": pending_requests,
        "recent_activity": recent_activity, "form": form, "doc_counts": doc_counts,
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


def paginate_article_body(body, words_per_page=550):
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    pages = []
    current_page = []
    current_words = 0
    for para in paragraphs:
        word_count = len(para.split())
        if current_page and current_words + word_count > words_per_page:
            pages.append(current_page)
            current_page = []
            current_words = 0
        current_page.append(para)
        current_words += word_count
    if current_page:
        pages.append(current_page)
    return pages or [[]]


def article_list(request):
    articles = Article.objects.filter(status="published")
    paginator = Paginator(articles, 10)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(request, "core/article_list.html", {"page_obj": page_obj})


def article_detail(request, slug):
    article = get_object_or_404(Article, slug=slug)
    if article.status != "published" and not request.user.is_staff:
        raise Http404
    pages = paginate_article_body(article.body)
    images = list(article.images.all())
    return render(request, "core/article_detail.html", {
        "article": article,
        "pages": pages,
        "images": images,
        "contact_email": "nwangailawadvocates@gmail.com",
        "contact_phone": "+254 714 535 492",
    })


def article_pdf(request, slug):
    article = get_object_or_404(Article, slug=slug)
    if article.status != "published" and not request.user.is_staff:
        raise Http404
    pages = paginate_article_body(article.body)
    images = list(article.images.all())
    template = get_template("core/article_pdf.html")
    html = template.render({
        "article": article,
        "pages": pages,
        "images": images,
        "contact_email": "nwangailawadvocates@gmail.com",
        "contact_phone": "+254 7XX XXX XXX",
    })
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{article.slug}.pdf"'
    result = pisa.CreatePDF(html, dest=response)
    if result.err:
        return HttpResponse("Could not generate the PDF for this article.", status=500)
    return response