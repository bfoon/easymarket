# accounts/forms.py
from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.crypto import get_random_string

User = get_user_model()


class CustomSignupForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    telephone = forms.CharField(max_length=200, required=False)
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"})
    )
    profile_picture = forms.ImageField(required=False)

    def _generate_username(self, email: str | None = None) -> str:
        email = email or ""
        base = (email.split("@")[0] or "user")[:20] or get_random_string(8).lower()
        candidate = base
        for _ in range(25):
            if not User.objects.filter(username=candidate).exists():
                return candidate
            candidate = f"{base}-{get_random_string(6).lower()}"[:30]
        return get_random_string(12).lower()

    def _apply_extra_fields(self, user):
        user.first_name = self.cleaned_data.get("first_name", "")
        user.last_name = self.cleaned_data.get("last_name", "")
        user.telephone = self.cleaned_data.get("telephone", "")

        # Ensure username exists (AbstractUser still has username)
        if not getattr(user, "username", None):
            # allauth may auto-populate; but be safe:
            email_from_request = getattr(user, "email", None)
            user.username = self._generate_username(email_from_request)

        pic = self.cleaned_data.get("profile_picture")
        if pic:
            user.profile_pic = pic  # your model field name

        user.save()

        # Optional: write DOB to a Profile model if you have one
        dob = self.cleaned_data.get("date_of_birth")
        if dob:
            try:
                from .models import Profile  # adjust/import only if exists
                Profile.objects.update_or_create(
                    user=user, defaults={"date_of_birth": dob}
                )
            except Exception:
                pass

        return user

    @transaction.atomic
    def signup(self, request, user):
        """
        Called by allauth AFTER the user has been created.
        Use this to copy extra fields to the user/profile.
        """
        return self._apply_extra_fields(user)


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "telephone"]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "First name"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Last name"}),
            "telephone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Phone"}),
        }
