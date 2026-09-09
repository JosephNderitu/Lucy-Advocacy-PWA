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
    return render(request, "core/about.html")


def contact(request):
    session_email = request.session.get('contact_email')
    conversation = None
    messages = []
    if session_email:
        conversation = Conversation.objects.filter(email=session_email).first()
        if conversation:
            messages = list(conversation.messages.values('sender', 'body', 'created_at'))
    return render(request, 'core/contact.html', {
        'session_email': session_email,
        'messages': messages,
    })
    
@require_POST
def send_verification_code(request):
    data = json.loads(request.body)
    email = data.get('email', '').strip().lower()
    if not email or '@' not in email:
        return JsonResponse({'error': 'Please enter a valid email address.'}, status=400)

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
    return JsonResponse({'success': True})


@require_POST
def verify_code(request):
    data = json.loads(request.body)
    email = data.get('email', '').strip().lower()
    code = data.get('code', '').strip()
    name = data.get('name', '').strip()

    verification = EmailVerification.objects.filter(
        email=email, code=code, is_used=False
    ).order_by('-created_at').first()

    if not verification:
        return JsonResponse({'error': 'Invalid code.'}, status=400)
    if verification.is_expired():
        return JsonResponse({'error': 'That code has expired. Request a new one.'}, status=400)

    verification.is_used = True
    verification.save(update_fields=['is_used'])

    conversation, created = Conversation.objects.get_or_create(email=email)
    if name and not conversation.name:
        conversation.name = name
        conversation.save(update_fields=['name'])

    request.session['contact_email'] = email
    request.session.set_expiry(60 * 60 * 24 * 30)  # keep them logged in for 30 days on this browser

    messages = list(conversation.messages.values('sender', 'body', 'created_at'))
    return JsonResponse({'success': True, 'messages': messages})


def get_messages(request):
    email = request.session.get('contact_email')
    if not email:
        return JsonResponse({'error': 'Not verified.'}, status=401)
    conversation = Conversation.objects.filter(email=email).first()
    if not conversation:
        return JsonResponse({'messages': []})
    messages = list(conversation.messages.values('sender', 'body', 'created_at'))
    return JsonResponse({'messages': messages})


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