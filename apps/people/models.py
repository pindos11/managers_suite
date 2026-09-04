from django.db import models

class Location(models.Model):
    name = models.CharField(max_length=120, unique=True)
    active = models.BooleanField(default=True)
    operating_hours = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    def __str__(self): return self.name

class Employee(models.Model):
    name = models.CharField(max_length=160)
    active = models.BooleanField(default=True)
    wish_priority = models.PositiveSmallIntegerField(default=1, help_text="1 (low) to 5 (high)")
    role = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True)
    allowed_locations = models.ManyToManyField(Location, through="EmployeeLocationEligibility", blank=True)
    def __str__(self): return self.name

class EmployeeLocationEligibility(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    location = models.ForeignKey(Location, on_delete=models.CASCADE)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    class Meta: unique_together = [("employee", "location", "starts_on")]
