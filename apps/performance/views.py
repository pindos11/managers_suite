from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .models import ManagerAlert, PerformanceReport

@login_required
def reports(request): return render(request, "performance/reports.html", {"reports": PerformanceReport.objects.select_related("employee", "location").all()[:200]})
@login_required
def alerts(request): return render(request, "performance/alerts.html", {"alerts": ManagerAlert.objects.select_related("employee").all()})
@login_required
def alert_status(request, pk, status):
    alert = get_object_or_404(ManagerAlert, pk=pk)
    if request.method == "POST" and status in dict(ManagerAlert._meta.get_field("status").choices):
        alert.status = status
        if status in [ManagerAlert.RESOLVED, ManagerAlert.DISMISSED]: alert.resolved_at = timezone.now()
        alert.manager_note = request.POST.get("note", alert.manager_note); alert.save()
    return redirect("alerts")
