# accounts/auth_backends.py
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

User = get_user_model()

class UsernameOrPhoneOrEmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        login = username or kwargs.get("login")
        if not login or not password:
            return None
        try:
            user = User.objects.get(
                Q(username__iexact=login) |
                Q(telephone__iexact=login) |   # your field name
                Q(email__iexact=login)
            )
        except User.DoesNotExist:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
