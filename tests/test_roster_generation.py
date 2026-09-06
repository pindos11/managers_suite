from datetime import date, datetime, time
import pytest
from apps.people.models import Employee, EmployeeLocationEligibility, Location
from apps.roster.models import RosterVersion, RosterWish, ShiftAssignment, ShiftTemplate
from apps.roster.services import coverage_for_roster, generate_roster

@pytest.mark.django_db
def test_generator_assigns_eligible_employee_and_reports_coverage():
    location = Location.objects.create(name="Main")
    employee = Employee.objects.create(name="Oksana")
    EmployeeLocationEligibility.objects.create(employee=employee, location=location)
    ShiftTemplate.objects.create(name="Day", location=location, start_time=time(9), end_time=time(17), min_headcount=1, max_headcount=1)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    generated, gaps = generate_roster(roster)
    assert generated == 28
    assert gaps == []
    assert all(row["gap"] == 0 for row in coverage_for_roster(roster))

@pytest.mark.django_db
def test_generator_prefers_wanted_date_using_employee_priority():
    location = Location.objects.create(name="Main")
    preferred = Employee.objects.create(name="Preferred", wish_priority=5)
    other = Employee.objects.create(name="Other", wish_priority=1)
    for employee in [preferred, other]: EmployeeLocationEligibility.objects.create(employee=employee, location=location)
    ShiftTemplate.objects.create(name="Day", location=location, start_time=time(9), end_time=time(17), min_headcount=1, max_headcount=1)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    RosterWish.objects.create(employee=preferred, starts_on=date(2026, 2, 1), ends_on=date(2026, 2, 1), date_preference=RosterWish.WANTED)
    generate_roster(roster)
    assert roster.assignments.get(starts_at__date=date(2026, 2, 1)).employee == preferred

@pytest.mark.django_db
def test_generator_adds_optional_staff_only_for_positive_wishes():
    location = Location.objects.create(name="Main")
    minimum = Employee.objects.create(name="Minimum")
    optional = Employee.objects.create(name="Optional", wish_priority=5)
    for employee in [minimum, optional]: EmployeeLocationEligibility.objects.create(employee=employee, location=location)
    ShiftTemplate.objects.create(name="Day", location=location, start_time=time(9), end_time=time(17), min_headcount=1, max_headcount=2)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    RosterWish.objects.create(employee=optional, starts_on=date(2026, 2, 1), ends_on=date(2026, 2, 1), date_preference=RosterWish.WANTED)
    generate_roster(roster)
    assert roster.assignments.filter(starts_at__date=date(2026, 2, 1)).count() == 2

@pytest.mark.django_db
def test_same_employee_cannot_be_added_twice_to_same_shift(client):
    from django.contrib.auth.models import User
    location = Location.objects.create(name="Main")
    employee = Employee.objects.create(name="Oksana")
    EmployeeLocationEligibility.objects.create(employee=employee, location=location)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    starts = "2026-02-01T09:00"; ends = "2026-02-01T17:00"
    from django.utils import timezone
    ShiftAssignment.objects.create(roster_version=roster, employee=employee, location=location, starts_at=timezone.make_aware(datetime.fromisoformat(starts)), ends_at=timezone.make_aware(datetime.fromisoformat(ends)))
    user = User.objects.create_user("manager", password="test")
    client.force_login(user)
    response = client.post(f"/roster/{roster.pk}/assignments/new/", {"employee": employee.pk, "location": location.pk, "starts_at": starts, "ends_at": ends, "override_reason": "needed"})
    assert response.status_code == 200
    assert roster.assignments.count() == 1

@pytest.mark.django_db
def test_manual_assignment_can_add_multiple_employees(client):
    from django.contrib.auth.models import User
    location = Location.objects.create(name="Main")
    first = Employee.objects.create(name="First")
    second = Employee.objects.create(name="Second")
    EmployeeLocationEligibility.objects.create(employee=first, location=location)
    EmployeeLocationEligibility.objects.create(employee=second, location=location)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    user = User.objects.create_user("manager", password="test")
    client.force_login(user)

    response = client.post(f"/roster/{roster.pk}/assignments/new/", {"employee": [first.pk, second.pk], "location": location.pk, "starts_at": "2026-02-10T09:00", "ends_at": "2026-02-10T17:00"})

    assert response.status_code == 302
    assert set(roster.assignments.values_list("employee_id", flat=True)) == {first.pk, second.pk}

@pytest.mark.django_db
def test_legacy_roster_import_uses_filled_cells_as_assignments(client):
    from django.contrib.auth.models import User
    location = Location.objects.create(name="Main")
    first = Employee.objects.create(name="First")
    second = Employee.objects.create(name="Second")
    for employee in [first, second]: EmployeeLocationEligibility.objects.create(employee=employee, location=location)
    template = ShiftTemplate.objects.create(name="Day", location=location, start_time=time(9), end_time=time(17), min_headcount=1, max_headcount=2)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    client.force_login(User.objects.create_user("manager", password="test"))

    response = client.post(f"/roster/{roster.pk}/import/", {"template": template.pk, "matrix": "Employee\t1\t2\nFirst\t8 h\t\nSecond\t\tWorked"})

    assert response.status_code == 302
    assert set(roster.assignments.values_list("employee_id", "starts_at__date")) == {(first.pk, date(2026, 2, 1)), (second.pk, date(2026, 2, 2))}

@pytest.mark.django_db
def test_legacy_roster_import_ignores_unknown_employee_rows(client):
    from django.contrib.auth.models import User
    location = Location.objects.create(name="Main")
    employee = Employee.objects.create(name="Known")
    EmployeeLocationEligibility.objects.create(employee=employee, location=location)
    template = ShiftTemplate.objects.create(name="Day", location=location, start_time=time(9), end_time=time(17), min_headcount=1, max_headcount=1)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    client.force_login(User.objects.create_user("manager", password="test"))

    response = client.post(f"/roster/{roster.pk}/import/", {"template": template.pk, "matrix": "Employee\t1\nUnknown\tWorked\nKnown\t8 h"}, follow=True)

    assert response.status_code == 200
    assert list(roster.assignments.values_list("employee_id", flat=True)) == [employee.pk]
    assert b"Ignored 1 row" in response.content
