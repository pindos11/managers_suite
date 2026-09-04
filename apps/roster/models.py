from django.db import models
from apps.people.models import Employee, Location

class ShiftTemplate(models.Model):
    name = models.CharField(max_length=80)
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    start_time = models.TimeField()
    end_time = models.TimeField()
    break_minutes = models.PositiveIntegerField(default=0)
    min_headcount = models.PositiveIntegerField(default=1, help_text="Minimum coverage required for this shift.")
    max_headcount = models.PositiveIntegerField(default=1, help_text="Maximum employees permitted on this shift.")
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.min_headcount > self.max_headcount:
            raise ValidationError({"max_headcount": "Maximum headcount must be equal to or greater than the minimum."})
    def __str__(self): return f"{self.name} — {self.location}"

class RosterVersion(models.Model):
    DRAFT, PUBLISHED, SUPERSEDED = "draft", "published", "superseded"
    STATUS = [(DRAFT, "Draft"), (PUBLISHED, "Published"), (SUPERSEDED, "Superseded")]
    month = models.DateField(help_text="First day of the month")
    status = models.CharField(max_length=12, choices=STATUS, default=DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    class Meta: ordering = ["-month", "-created_at"]
    def __str__(self): return f"{self.month:%B %Y} ({self.status})"

class ShiftAssignment(models.Model):
    roster_version = models.ForeignKey(RosterVersion, related_name="assignments", on_delete=models.CASCADE)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT)
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    source = models.CharField(max_length=20, default="manual")
    override_reason = models.TextField(blank=True)
    class Meta: ordering = ["starts_at"]

class RosterGenerationRun(models.Model):
    PREVIEW, APPLIED, INVALID = "preview", "applied", "invalid"
    STATUS = [(PREVIEW, "Preview"), (APPLIED, "Applied"), (INVALID, "Invalid")]
    roster_version = models.ForeignKey(RosterVersion, related_name="generation_runs", on_delete=models.CASCADE)
    planning_starts_on = models.DateField(null=True, blank=True, help_text="First date the solver may change.")
    status = models.CharField(max_length=12, choices=STATUS, default=PREVIEW)
    input_fingerprint = models.CharField(max_length=64)
    summary = models.JSONField(default=dict)
    diagnostics = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    class Meta: ordering = ["-created_at"]

class RosterGenerationProposalAssignment(models.Model):
    generation_run = models.ForeignKey(RosterGenerationRun, related_name="proposed_assignments", on_delete=models.CASCADE)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT)
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    wish_score = models.IntegerField(default=0)
    class Meta: ordering = ["starts_at", "employee__name"]

class Availability(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    available = models.BooleanField(default=False)
    source = models.CharField(max_length=50, default="manager")
    notes = models.TextField(blank=True)

class RosterWish(models.Model):
    WANTED, UNWANTED, NEUTRAL = "wanted", "unwanted", "neutral"
    DATE_PREFERENCE = [(WANTED, "Wanted"), (UNWANTED, "Unwanted"), (NEUTRAL, "No date preference")]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    starts_on = models.DateField()
    ends_on = models.DateField()
    preferred_location = models.ForeignKey(Location, null=True, blank=True, on_delete=models.SET_NULL)
    preferred_weekdays = models.JSONField(default=list, blank=True, help_text="Weekday numbers: Monday is 0, Sunday is 6.")
    date_preference = models.CharField(max_length=12, choices=DATE_PREFERENCE, default=NEUTRAL)
    desired_day_off = models.BooleanField(default=False)
    note = models.TextField(blank=True)
    @property
    def preferred_weekday_names(self):
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        return ", ".join(names[day] for day in self.preferred_weekdays if 0 <= day <= 6)

class Absence(models.Model):
    PENDING, APPROVED = "pending", "approved"
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    category = models.CharField(max_length=80)
    status = models.CharField(max_length=12, choices=[(PENDING, "Pending"), (APPROVED, "Approved")], default=PENDING)
    notes = models.TextField(blank=True)
