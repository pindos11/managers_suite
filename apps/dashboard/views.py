from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from apps.performance.models import ManagerAlert, PerformanceReport
from apps.roster.models import ShiftAssignment, RosterVersion

@login_required
def dashboard(request):
    now = timezone.now()
    assignments = ShiftAssignment.objects.filter(roster_version__status=RosterVersion.PUBLISHED, starts_at__lte=now, ends_at__gte=now).select_related("employee", "location")
    reports = PerformanceReport.objects.filter(status=PerformanceReport.ACCEPTED).select_related("employee", "location")[:10]
    return render(request, "dashboard/home.html", {"assignments": assignments, "reports": reports, "alerts": ManagerAlert.objects.filter(status=ManagerAlert.OPEN).select_related("employee")[:10]})

def health(request):
    connection.ensure_connection()
    return JsonResponse({"status": "ok", "database": "connected"})
