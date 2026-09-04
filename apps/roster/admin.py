from django.contrib import admin
from .models import Absence, Availability, RosterVersion, RosterWish, ShiftAssignment, ShiftTemplate
admin.site.register([Absence, Availability, RosterVersion, RosterWish, ShiftAssignment, ShiftTemplate])
