from django.contrib import admin
from .models import Employee, EmployeeLocationEligibility, Location
admin.site.register([Employee, EmployeeLocationEligibility, Location])
