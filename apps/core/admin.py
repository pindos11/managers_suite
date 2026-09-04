from django.contrib import admin
from .models import AuditEvent, WorkerHeartbeat
admin.site.register([AuditEvent, WorkerHeartbeat])
