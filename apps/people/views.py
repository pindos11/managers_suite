from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from .forms import EmployeeForm, LocationForm
from .models import Employee, Location

@login_required
def employees(request):
    q = request.GET.get("q", "")
    return render(request, "people/employees.html", {"employees": Employee.objects.filter(name__icontains=q).order_by("name"), "q": q})

@login_required
def employee_edit(request, pk=None):
    form = EmployeeForm(request.POST or None, instance=get_object_or_404(Employee, pk=pk) if pk else None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("employees")
    return render(request, "form.html", {"form": form, "title": _("Employee")})

@login_required
def locations(request):
    return render(request, "people/locations.html", {"locations": Location.objects.order_by("name")})

@login_required
def location_edit(request, pk=None):
    form = LocationForm(request.POST or None, instance=get_object_or_404(Location, pk=pk) if pk else None)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("locations")
    return render(request, "form.html", {"form": form, "title": _("Location")})
