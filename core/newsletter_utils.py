from django.conf import settings
from django.core import mail, signing

UNSUBSCRIBE_SALT = "newsletter-unsubscribe"
UNSUBSCRIBE_MAX_AGE = 60 * 60 * 24 * 365


def make_unsubscribe_token(subscriber_id):
    return signing.dumps(subscriber_id, salt=UNSUBSCRIBE_SALT)


def read_unsubscribe_token(token):
    return signing.loads(token, salt=UNSUBSCRIBE_SALT, max_age=UNSUBSCRIBE_MAX_AGE)


def get_newsletter_connection():
    """Django 6.1's MAILERS setting already fully describes the 'default'
    mailer, so we just ask for that configured instance rather than
    rebuilding a connection from individual host/port/tls arguments."""
    return mail.mailers["default"]