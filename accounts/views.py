from django.shortcuts import render, redirect
from django.contrib.auth import login, get_user_model

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
