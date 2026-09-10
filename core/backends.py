# New file: core/backends.py
from django.contrib.auth.backends import BaseBackend
from django.contrib.auth import get_user_model
from .models import Case

User = get_user_model()


class CaseCredentialsBackend(BaseBackend):
    """
    Authenticates a client using their case number + national ID number
    instead of username/password. Register in settings.AUTHENTICATION_BACKENDS
    alongside Django's default ModelBackend (which still handles admin/staff
    username+password logins).
    """

    def authenticate(self, request, case_number=None, id_no=None, **kwargs):
        if not case_number or not id_no:
            return None
        try:
            case = Case.objects.select_related("client__user").get(
                case_number__iexact=case_number.strip()
            )
        except Case.DoesNotExist:
            return None

        profile = case.client
        if profile.id_no.strip().lower() != id_no.strip().lower():
            return None
        if not profile.user.is_active:
            return None
        return profile.user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None