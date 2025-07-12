from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from marketplace.utils import migrate_session_cart_to_user

@receiver(user_logged_in)
def move_session_cart_on_login(sender, request, user, **kwargs):
    migrate_session_cart_to_user(request, user)
