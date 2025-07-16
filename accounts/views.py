from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, get_user_model
from django.contrib.auth import authenticate, login, logout
from .models import User
from .models import Address
from marketplace.utils import migrate_session_cart_to_user
from django.contrib import messages
from .forms import UserRegisterForm
from django.contrib.auth.hashers import make_password
from django.utils.text import slugify


def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            if request.session.get('checkout_after_login'):
                # Migrate cart and redirect to resume checkout
                migrate_session_cart_to_user(request, user)
                del request.session['checkout_after_login']  # Clean up
                return redirect('orders:checkout_redirect')

            messages.success(request, f"Welcome back, {user.username}!")
            return redirect('/')  # ✅ Replace with user dashboard or homepage
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'accounts/login.html')

def custom_logout(request):
    logout(request)
    return redirect('marketplace:product_list')

def generate_unique_username(email):
    base_username = slugify(email.split('@')[0])
    username = base_username
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1
    return username


def register_view(request):
    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        telephone = request.POST.get('phone')
        profile_pic = request.FILES.get('profile_picture')

        if password != password_confirm:
            messages.error(request, "Passwords do not match.")
            return redirect('accounts:register')

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email is already in use.")
            return redirect('accounts:register')

        username = generate_unique_username(email)

        user = User.objects.create(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            telephone=telephone,
            profile_pic=profile_pic,
            is_buyer=True,
            password=make_password(password)
        )

        login(request, user)
        messages.success(request, "Account created successfully.")
        return redirect('/')
    else:
        return render(request, 'accounts/register.html')

@login_required
def edit_address_modal(request):
    address, created = Address.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        address.address1 = request.POST.get('address1', '').strip()
        address.address2 = request.POST.get('address2', '').strip()
        address.country = request.POST.get('country', '').strip()
        address.geo_code = request.POST.get('geo_code', '').strip()  # Include geo code
        address.save()
        return redirect(request.META.get('HTTP_REFERER', 'marketplace:product_list'))

    return redirect('marketplace:product_list')