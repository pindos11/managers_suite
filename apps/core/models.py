from django.conf import settings
from django.db import models

class AuditEvent(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    event_type = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=64)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)

class WorkerHeartbeat(models.Model):
    worker_name = models.CharField(max_length=50, unique=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    detail = models.CharField(max_length=255, blank=True)
