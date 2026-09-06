from django.db import models
from django.utils.translation import gettext_lazy as _

class Location(models.Model):
    name = models.CharField(_("Name"), max_length=120, unique=True)
    active = models.BooleanField(_("Active"), default=True)
    operating_hours = models.CharField(_("Operating hours"), max_length=100, blank=True)
    notes = models.TextField(_("Notes"), blank=True)
    def __str__(self): return self.name

class Employee(models.Model):
    name = models.CharField(_("Name"), max_length=160)
    active = models.BooleanField(_("Active"), default=True)
    wish_priority = models.PositiveSmallIntegerField(_("Wish priority"), default=1, help_text=_("1 (low) to 5 (high)"))
    role = models.CharField(_("Role"), max_length=80, blank=True)
    notes = models.TextField(_("Notes"), blank=True)
    allowed_locations = models.ManyToManyField(Location, verbose_name=_("Allowed locations"), through="EmployeeLocationEligibility", blank=True)
    def __str__(self): return self.name

class EmployeeLocationEligibility(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    location = models.ForeignKey(Location, on_delete=models.CASCADE)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    class Meta: unique_together = [("employee", "location", "starts_on")]
