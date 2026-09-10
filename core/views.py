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


def home(request):
    practice_areas = list(
        PracticeArea.objects.filter(is_active=True).values(
            "id", "title", "description", "icon_class"
        )
    )
    return render(request, "core/home.html", {"practice_areas": practice_areas})


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
                           .values('sender', 'body', 'created_at'))
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
        cache.set(attempts_key, attempts + 1, timeout=600)  # matches code's 10-min lifetime
        return JsonResponse({'error': 'Invalid code.'}, status=400)

    if verification.is_expired():
        cache.set(attempts_key, attempts + 1, timeout=600)
        return JsonResponse({'error': 'That code has expired. Request a new one.'}, status=400)

    cache.delete(attempts_key)  # reset on success

    verification.is_used = True
    verification.save(update_fields=['is_used'])

    conversation, created = Conversation.objects.get_or_create(email=email)
    if name and not conversation.name:
        conversation.name = name
        conversation.save(update_fields=['name'])

    request.session['contact_email'] = email
    request.session.set_expiry(60 * 60 * 24 * 30)

    messages = list(conversation.messages.values('sender', 'body', 'created_at'))
    return JsonResponse({'success': True, 'messages': messages})


def get_messages(request):
    email = request.session.get('contact_email')
    if not email:
        return JsonResponse({'error': 'Not verified.'}, status=401)

    conversation = Conversation.objects.filter(email=email).first()
    if not conversation:
        return JsonResponse({'messages': [], 'has_more': False})

    before = request.GET.get('before')
    qs = conversation.messages.order_by('-created_at')
    if before:
        qs = qs.filter(created_at__lt=before)

    page = list(qs[:MESSAGES_PAGE_SIZE].values('sender', 'body', 'created_at'))
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
    ChatMessage.objects.create(conversation=conversation, sender='guest', body=body)
    conversation.last_message_at = timezone.now()
    conversation.save(update_fields=['last_message_at'])

    return JsonResponse({'success': True})


def contact_logout(request):
    request.session.pop('contact_email', None)
    return JsonResponse({'success': True})

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import NewsletterSubscriber
from .newsletter_utils import read_unsubscribe_token


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