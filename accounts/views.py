from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, get_user_model
from .models import Address

def register_buyer(request):
    UserModel = get_user_model()
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        if username and password:
            user = UserModel.objects.create_user(username=username, password=password, is_buyer=True)
            login(request, user)
            return redirect('marketplace:product_list')
    return render(request, 'accounts/register_buyer.html')

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