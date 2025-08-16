# accounts/forms.py
from django import forms
from django.contrib.auth import get_user_model
from django.db import transaction

User = get_user_model()

class CustomSignupForm(forms.Form):
    # Email optional (since ACCOUNT_EMAIL_REQUIRED=False)
    email = forms.EmailField(required=False, label="Email (optional)")

    # Your required extras
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=True)
    telephone = forms.CharField(label="Phone number", max_length=32, required=True)

    # Optional extras
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    profile_picture = forms.ImageField(required=False)

    # Uniqueness checks for values we own here
    def clean_telephone(self):
        tel = self.cleaned_data["telephone"].strip()
        if User.objects.filter(telephone__iexact=tel).exists():
            raise forms.ValidationError("This phone number is already in use.")
        return tel

    def clean_email(self):
        e = (self.cleaned_data.get("email") or "").strip()
        if e and User.objects.filter(email__iexact=e).exists():
            raise forms.ValidationError("This email is already in use.")
        return e or None

    @transaction.atomic
    def signup(self, request, user):
        """
        Called by allauth AFTER the base user is created (username/password handled by allauth).
        Attach extras here.
        """
        user.first_name = self.cleaned_data.get("first_name", "")
        user.last_name = self.cleaned_data.get("last_name", "")
        user.telephone = self.cleaned_data["telephone"]
        if self.cleaned_data.get("email"):
            user.email = self.cleaned_data["email"]

        pic = self.cleaned_data.get("profile_picture")
        if pic and hasattr(user, "profile_pic"):
            user.profile_pic = pic

        user.save()

        dob = self.cleaned_data.get("date_of_birth")
        if dob:
            try:
                from .models import Profile
                Profile.objects.update_or_create(user=user, defaults={"date_of_birth": dob})
            except Exception:
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
