from datetime import date, datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.people.models import Employee, Location
from apps.roster.models import RosterVersion, ShiftAssignment


@pytest.mark.django_db
def test_deleting_a_roster_removes_its_assignments(client, django_user_model):
    user = django_user_model.objects.create_user(username="manager", password="secret")
    client.force_login(user)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    employee = Employee.objects.create(name="A very long employee name")
    location = Location.objects.create(name="Main")
    ShiftAssignment.objects.create(
        roster_version=roster,
        employee=employee,
        location=location,
        starts_at=timezone.make_aware(datetime(2026, 2, 1, 9)),
        ends_at=timezone.make_aware(datetime(2026, 2, 1, 17)),
    )

    response = client.post(reverse("roster_delete", args=[roster.pk]))

    assert response.status_code == 302
    assert response.url == reverse("rosters")
    assert not RosterVersion.objects.filter(pk=roster.pk).exists()
    assert not ShiftAssignment.objects.exists()


@pytest.mark.django_db
def test_roster_delete_confirmation_is_displayed(client, django_user_model):
    user = django_user_model.objects.create_user(username="manager", password="secret")
    client.force_login(user)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))

    response = client.get(reverse("roster_delete", args=[roster.pk]))

    assert response.status_code == 200
    assert b"Delete roster" in response.content
    assert RosterVersion.objects.filter(pk=roster.pk).exists()
