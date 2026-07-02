from django.contrib import messages
from django.shortcuts import redirect, render

from .forms import AccountActivationForm


def activate_account(request):
    form = AccountActivationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Учетная запись активирована. Теперь можно войти в систему.")
        return redirect("login")
    return render(request, "registration/activate_account.html", {"form": form})
