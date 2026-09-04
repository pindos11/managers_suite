from django.contrib import admin
from .models import AlertRule, EmployeeTargetAllocation, LocationTarget, ManagerAlert, PerformanceReport
admin.site.register([AlertRule, EmployeeTargetAllocation, LocationTarget, ManagerAlert, PerformanceReport])
