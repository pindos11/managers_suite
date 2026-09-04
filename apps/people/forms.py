from django import forms
from .models import Employee, Location

class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ["name", "active", "wish_priority", "role", "notes", "allowed_locations"]

class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ["name", "active", "operating_hours", "notes"]
