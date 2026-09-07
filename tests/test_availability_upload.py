import json
from datetime import date, datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.people.models import Employee
from apps.roster.models import Availability


def upload(payload):
    return SimpleUploadedFile("availability-2026-10.json", json.dumps(payload).encode("utf-8-sig"), content_type="application/json")


@pytest.mark.django_db
def test_json_upload_replaces_one_month_with_available_and_unavailable_days(client, django_user_model):
    user = django_user_model.objects.create_user(username="manager", password="secret")
    client.force_login(user)
    employee = Employee.objects.create(name="Ada Lovelace")
    zone = ZoneInfo("Europe/Kyiv")
    Availability.objects.create(employee=employee, starts_at=datetime(2026, 10, 2, tzinfo=zone), ends_at=datetime(2026, 10, 3, tzinfo=zone), available=True)

    response = client.post(reverse("availability_upload"), {"file": upload({"employee_name": "Ada Lovelace", "selected_dates": ["2026-10-03", "2026-10-14"]})})

    assert response.status_code == 302
    records = Availability.objects.filter(employee=employee, starts_at__date__gte=date(2026, 10, 1)).order_by("starts_at")
    assert records.count() == 31
    assert {timezone.localtime(record.starts_at).date() for record in records if record.available} == {date(2026, 10, 3), date(2026, 10, 14)}
    assert all(timezone.localtime(record.ends_at).date() == timezone.localtime(record.starts_at).date() + timedelta(days=1) for record in records)


@pytest.mark.django_db
def test_json_upload_rejects_multiple_months_without_changing_availability(client, django_user_model):
    user = django_user_model.objects.create_user(username="manager", password="secret")
    client.force_login(user)
    employee = Employee.objects.create(name="Ada Lovelace")
    existing = Availability.objects.create(employee=employee, starts_at=datetime(2026, 10, 2, tzinfo=ZoneInfo("Europe/Kyiv")), ends_at=datetime(2026, 10, 3, tzinfo=ZoneInfo("Europe/Kyiv")), available=True)

    response = client.post(reverse("availability_upload"), {"file": upload({"employee_name": "Ada Lovelace", "selected_dates": ["2026-10-03", "2026-11-01"]})})

    assert response.status_code == 200
    assert "exactly one month" in response.content.decode()
    assert list(Availability.objects.values_list("pk", flat=True)) == [existing.pk]


@pytest.mark.django_db
def test_json_upload_requires_exact_employee_name(client, django_user_model):
    user = django_user_model.objects.create_user(username="manager", password="secret")
    client.force_login(user)
    Employee.objects.create(name="Ada Lovelace")

    response = client.post(reverse("availability_upload"), {"file": upload({"employee_name": "ada lovelace", "selected_dates": ["2026-10-03"]})})

    assert response.status_code == 200
    assert "exactly match one employee" in response.content.decode()
    assert not Availability.objects.exists()
