from django.core import signing

UNSUBSCRIBE_SALT = "newsletter-unsubscribe"
UNSUBSCRIBE_MAX_AGE = 60 * 60 * 24 * 365  # link stays valid for 1 year


def make_unsubscribe_token(subscriber_id):
    return signing.dumps(subscriber_id, salt=UNSUBSCRIBE_SALT)


def read_unsubscribe_token(token):
    """Returns the subscriber id. Raises signing.BadSignature or
    signing.SignatureExpired if the link is invalid or too old."""
    return signing.loads(token, salt=UNSUBSCRIBE_SALT, max_age=UNSUBSCRIBE_MAX_AGE)