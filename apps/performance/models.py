from django.db import models
from apps.people.models import Employee, Location
from apps.roster.models import ShiftAssignment

class LocationTarget(models.Model):
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    starts_on = models.DateField()
    ends_on = models.DateField()
    target_total = models.PositiveIntegerField()
    active = models.BooleanField(default=True)
    class Meta: ordering = ["-starts_on"]

class EmployeeTargetAllocation(models.Model):
    target = models.ForeignKey(LocationTarget, related_name="allocations", on_delete=models.CASCADE)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT)
    allocated_target = models.PositiveIntegerField()
    class Meta: unique_together = [("target", "employee")]

class PerformanceReport(models.Model):
    ACCEPTED, SUPERSEDED, REVIEW = "accepted", "superseded", "review"
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT)
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    assignment = models.ForeignKey(ShiftAssignment, null=True, blank=True, on_delete=models.SET_NULL)
    reported_at = models.DateTimeField()
    employee_total = models.PositiveIntegerField()
    location_total = models.PositiveIntegerField()
    status = models.CharField(max_length=12, default=ACCEPTED)
    replaces = models.ForeignKey("self", null=True, blank=True, related_name="corrections", on_delete=models.SET_NULL)
    class Meta: ordering = ["-reported_at"]

class AlertRule(models.Model):
    MISSING, PACE, NO_INCREASE = "missing", "pace", "no_increase"
    rule_type = models.CharField(max_length=20, choices=[(MISSING,"Missing report"),(PACE,"Below pace"),(NO_INCREASE,"No increase")])
    enabled = models.BooleanField(default=True)
    threshold = models.FloatField(default=0)
    grace_minutes = models.PositiveIntegerField(default=30)
    severity = models.CharField(max_length=12, default="warning")

class ManagerAlert(models.Model):
    OPEN, ACKNOWLEDGED, RESOLVED, DISMISSED = "open", "acknowledged", "resolved", "dismissed"
    rule = models.ForeignKey(AlertRule, null=True, blank=True, on_delete=models.SET_NULL)
    employee = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.SET_NULL)
    assignment = models.ForeignKey(ShiftAssignment, null=True, blank=True, on_delete=models.SET_NULL)
    report = models.ForeignKey(PerformanceReport, null=True, blank=True, on_delete=models.SET_NULL)
    severity = models.CharField(max_length=12, default="warning")
    status = models.CharField(max_length=16, default=OPEN)
    explanation = models.TextField()
    manager_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
