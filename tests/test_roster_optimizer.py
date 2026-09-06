from datetime import date, time
import pytest
from apps.people.models import Employee, EmployeeLocationEligibility, Location
from apps.roster.models import RosterEmployeeTarget, RosterGenerationProposalAssignment, RosterGenerationRun, RosterVersion, RosterWish, ShiftAssignment, ShiftTemplate
from apps.roster.services import RosterOptimizationService, _wish_score, proposal_delta, proposal_workload_delta, roster_calendar

@pytest.mark.django_db
def test_optimizer_prioritizes_monthly_targets_before_optional_capacity():
    location = Location.objects.create(name="Main")
    targeted = Employee.objects.create(name="Targeted")
    other = Employee.objects.create(name="Other")
    for employee in [targeted, other]: EmployeeLocationEligibility.objects.create(employee=employee, location=location)
    ShiftTemplate.objects.create(name="Day", location=location, start_time=time(9), end_time=time(17), min_headcount=1, max_headcount=1)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    RosterEmployeeTarget.objects.create(roster_version=roster, employee=targeted, target_shifts=28)

    preview = RosterOptimizationService(roster).create_preview()

    assert preview.proposed_assignments.filter(employee=targeted).count() == 28

@pytest.mark.django_db
def test_optimizer_previews_then_applies_maximum_feasible_capacity():
    location = Location.objects.create(name="Main")
    employees = [Employee.objects.create(name=f"Employee {number}") for number in range(3)]
    for employee in employees: EmployeeLocationEligibility.objects.create(employee=employee, location=location)
    ShiftTemplate.objects.create(name="Day", location=location, start_time=time(9), end_time=time(17), min_headcount=1, max_headcount=3)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    preview = RosterOptimizationService(roster).create_preview()
    assert preview.status == RosterGenerationRun.PREVIEW
    assert roster.assignments.count() == 0
    assert preview.proposed_assignments.count() == 84
    RosterOptimizationService.apply_preview(preview)
    assert preview.status == RosterGenerationRun.APPLIED
    assert roster.assignments.filter(source="solver_generated").count() == 84

@pytest.mark.django_db
def test_optimizer_preserves_manual_assignment_and_rejects_stale_preview():
    location = Location.objects.create(name="Main")
    manual, other = Employee.objects.create(name="Manual"), Employee.objects.create(name="Other")
    for employee in [manual, other]: EmployeeLocationEligibility.objects.create(employee=employee, location=location)
    ShiftTemplate.objects.create(name="Day", location=location, start_time=time(9), end_time=time(17), min_headcount=1, max_headcount=2)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    from apps.roster.services import shift_datetimes
    starts, ends = shift_datetimes(date(2026, 2, 1), ShiftTemplate.objects.get())
    locked = ShiftAssignment.objects.create(roster_version=roster, employee=manual, location=location, starts_at=starts, ends_at=ends, source="manual")
    preview = RosterOptimizationService(roster).create_preview()
    locked.override_reason = "manager changed this assignment"; locked.save()
    with pytest.raises(ValueError, match="changed"):
        RosterOptimizationService.apply_preview(preview)

@pytest.mark.django_db
def test_applying_preview_keeps_manual_shifts():
    location = Location.objects.create(name="Main")
    manual, other = Employee.objects.create(name="Manual"), Employee.objects.create(name="Other")
    for employee in [manual, other]: EmployeeLocationEligibility.objects.create(employee=employee, location=location)
    template = ShiftTemplate.objects.create(name="Day", location=location, start_time=time(9), end_time=time(17), min_headcount=1, max_headcount=2)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    from apps.roster.services import shift_datetimes
    starts, ends = shift_datetimes(date(2026, 2, 1), template)
    locked = ShiftAssignment.objects.create(roster_version=roster, employee=manual, location=location, starts_at=starts, ends_at=ends, source="manual")
    preview = RosterOptimizationService(roster).create_preview()
    RosterOptimizationService.apply_preview(preview)
    assert ShiftAssignment.objects.filter(pk=locked.pk, source="manual").exists()

@pytest.mark.django_db
def test_proposal_delta_compares_preview_against_current_draft():
    location = Location.objects.create(name="Main")
    old, new = Employee.objects.create(name="Old"), Employee.objects.create(name="New")
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    from django.utils import timezone
    from datetime import datetime
    starts = timezone.make_aware(datetime(2026, 2, 1, 9)); ends = timezone.make_aware(datetime(2026, 2, 1, 17))
    ShiftAssignment.objects.create(roster_version=roster, employee=old, location=location, starts_at=starts, ends_at=ends, source="solver_generated")
    run = RosterGenerationRun.objects.create(roster_version=roster, input_fingerprint="test")
    RosterGenerationProposalAssignment.objects.create(generation_run=run, employee=new, location=location, starts_at=starts, ends_at=ends)
    assert [(row["change"], row["assignment"].employee) for row in proposal_delta(run)] == [("added", new), ("removed", old)]

@pytest.mark.django_db
def test_weekday_wish_penalizes_other_days_only_in_validity_period():
    location = Location.objects.create(name="Main")
    employee = Employee.objects.create(name="Preference", wish_priority=3)
    wish = RosterWish.objects.create(employee=employee, starts_on=date(2026, 2, 2), ends_on=date(2026, 2, 8), preferred_weekdays=[0])
    wishes = {employee.pk: [wish]}
    assert _wish_score(employee, location, date(2026, 2, 2), wishes) == 3
    assert _wish_score(employee, location, date(2026, 2, 3), wishes) == -3
    assert _wish_score(employee, location, date(2026, 2, 9), wishes) == 0

@pytest.mark.django_db
def test_partial_regeneration_preserves_prior_assignments_and_balances_from_start_date():
    location = Location.objects.create(name="Main")
    prior_employee, future_employee = Employee.objects.create(name="Prior"), Employee.objects.create(name="Future")
    for employee in [prior_employee, future_employee]: EmployeeLocationEligibility.objects.create(employee=employee, location=location)
    template = ShiftTemplate.objects.create(name="Day", location=location, start_time=time(9), end_time=time(17), min_headcount=1, max_headcount=1)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    from apps.roster.services import shift_datetimes
    starts, ends = shift_datetimes(date(2026, 2, 1), template)
    prior = ShiftAssignment.objects.create(roster_version=roster, employee=prior_employee, location=location, starts_at=starts, ends_at=ends, source="solver_generated")
    preview = RosterOptimizationService(roster, date(2026, 2, 15)).create_preview()
    assert preview.planning_starts_on == date(2026, 2, 15)
    assert all(row.starts_at.date() >= date(2026, 2, 15) for row in preview.proposed_assignments.all())
    RosterOptimizationService.apply_preview(preview)
    assert ShiftAssignment.objects.filter(pk=prior.pk).exists()

@pytest.mark.django_db
def test_partial_regeneration_prefers_existing_feasible_generated_assignment():
    location = Location.objects.create(name="Main")
    alternative, retained = Employee.objects.create(name="Alternative"), Employee.objects.create(name="Retained")
    for employee in [alternative, retained]: EmployeeLocationEligibility.objects.create(employee=employee, location=location)
    template = ShiftTemplate.objects.create(name="Day", location=location, start_time=time(9), end_time=time(17), min_headcount=1, max_headcount=1)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    from apps.roster.services import shift_datetimes
    starts, ends = shift_datetimes(date(2026, 2, 15), template)
    ShiftAssignment.objects.create(roster_version=roster, employee=retained, location=location, starts_at=starts, ends_at=ends, source="solver_generated")

    preview = RosterOptimizationService(roster, date(2026, 2, 15)).create_preview()
    kept = preview.proposed_assignments.get(starts_at=starts)
    assert kept.employee == retained
    assert preview.summary["retained_assignments"] >= 1

@pytest.mark.django_db
def test_preview_calendar_shows_weekends_staffing_delta_and_workload_before_after():
    location = Location.objects.create(name="Main")
    old, new = Employee.objects.create(name="Old"), Employee.objects.create(name="New")
    template = ShiftTemplate.objects.create(name="Day", location=location, start_time=time(9), end_time=time(17), min_headcount=1, max_headcount=1)
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))
    from apps.roster.services import shift_datetimes
    starts, ends = shift_datetimes(date(2026, 2, 15), template)
    ShiftAssignment.objects.create(roster_version=roster, employee=old, location=location, starts_at=starts, ends_at=ends, source="solver_generated")
    run = RosterGenerationRun.objects.create(roster_version=roster, planning_starts_on=date(2026, 2, 15), input_fingerprint="test")
    RosterGenerationProposalAssignment.objects.create(generation_run=run, employee=new, location=location, starts_at=starts, ends_at=ends)

    weeks = roster_calendar(roster, run)
    assert len(weeks) == 5
    assert weeks[0][5]["is_weekend"] and weeks[0][6]["is_weekend"]
    shift = next(shift for week in weeks for cell in week for shift in cell["shifts"] if shift["starts_at"] == starts)
    assert (shift["assigned_count"], shift["previous_count"], shift["delta"]) == (1, 1, 0)
    assert [row.employee for row in shift["added_assignments"]] == [new]
    assert [row.employee for row in shift["removed_assignments"]] == [old]
    workloads = {row["employee"].name: row for row in proposal_workload_delta(run)}
    assert (workloads["Old"]["before_shifts"], workloads["Old"]["after_shifts"]) == (1, 0)
    assert (workloads["New"]["before_days"], workloads["New"]["after_days"]) == (0, 1)
