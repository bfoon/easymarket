# accounts/forms.py
from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction
import re

User = get_user_model()


_phone_re = re.compile(r"[^\d+]")  # allow digits and leading '+'

def normalize_phone(raw: str) -> str:
    raw = (raw or "").strip()
    # keep '+' if present, drop any other non-digits
    if raw.startswith("+"):
        return "+" + _phone_re.sub("", raw)[1:]
    return _phone_re.sub("", raw)

class CustomSignupForm(forms.Form):
    # Email optional
    email = forms.EmailField(required=False, label="Email (optional)")

    # Required extras
    first_name = forms.CharField(max_length=150, required=True)
    last_name  = forms.CharField(max_length=150, required=True)
    telephone  = forms.CharField(label="Phone number", max_length=32, required=True)

    # Optional extras
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    profile_picture = forms.ImageField(required=False)

    # ---- Cleaners -----------------------------------------------------------
    def clean_telephone(self):
        tel = normalize_phone(self.cleaned_data["telephone"])
        if not tel:
            raise forms.ValidationError("Please enter a valid phone number.")
        # Your model has unique=True on telephone → preempt IntegrityError
        if User.objects.filter(telephone__iexact=tel).exists():
            raise forms.ValidationError("This phone number is already in use.")
        return tel

    def clean_email(self):
        e = (self.cleaned_data.get("email") or "").strip().lower()
        if e and User.objects.filter(email__iexact=e).exists():
            raise forms.ValidationError("This email is already in use.")
        return e or None  # store None when blank

    # ---- Hook called by django-allauth after base user creation ------------
    @transaction.atomic
    def signup(self, request, user):
        user.first_name = self.cleaned_data.get("first_name", "")
        user.last_name  = self.cleaned_data.get("last_name", "")
        user.telephone  = self.cleaned_data["telephone"]    # required
        if self.cleaned_data.get("email"):
            user.email = self.cleaned_data["email"]

        # Default buyer role (adjust if you prefer another default)
        if hasattr(user, "is_buyer"):
            user.is_buyer = True

        pic = self.cleaned_data.get("profile_picture")
        if pic and hasattr(user, "profile_pic"):
            user.profile_pic = pic

        user.save()

        # Optional: attach DOB to a Profile model if you have one
        dob = self.cleaned_data.get("date_of_birth")
        if dob:
            try:
                from .models import Profile  # only if it exists in your app
                Profile.objects.update_or_create(user=user, defaults={"date_of_birth": dob})
            except Exception:
                # silently ignore if Profile doesn't exist
                pass
        return user


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "telephone"]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "First name"}),
            "last_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Last name"}),
            "telephone": forms.TextInput(attrs={"class": "form-control", "placeholder": "Phone"}),
        }
