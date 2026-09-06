import hashlib
import json
from calendar import Calendar
from collections import defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
from django.db import models, transaction
from django.utils.translation import gettext as _
from apps.people.models import Employee
from .models import Absence, Availability, RosterGenerationProposalAssignment, RosterGenerationRun, RosterVersion, RosterWish, ShiftAssignment, ShiftTemplate

def eligible_for_shift(employee, location, starts_at, ends_at, roster=None, assignment_sources=None):
    if not employee.active or not employee.allowed_locations.filter(pk=location.pk).exists(): return False, _("not eligible for this location")
    if Absence.objects.filter(employee=employee, status=Absence.APPROVED, starts_at__lt=ends_at, ends_at__gt=starts_at).exists(): return False, _("approved absence")
    if Availability.objects.filter(employee=employee, available=False, starts_at__lt=ends_at, ends_at__gt=starts_at).exists(): return False, _("marked unavailable")
    assignments = ShiftAssignment.objects.filter(employee=employee, starts_at__lt=ends_at, ends_at__gt=starts_at)
    if roster: assignments = assignments.filter(roster_version=roster)
    if assignment_sources is not None: assignments = assignments.filter(source__in=assignment_sources)
    if assignments.exists(): return False, _("overlapping shift")
    return True, ""

def shift_datetimes(day, template):
    zone = ZoneInfo(settings.BUSINESS_TIME_ZONE)
    starts_at = datetime.combine(day, template.start_time, tzinfo=zone)
    ends_at = datetime.combine(day, template.end_time, tzinfo=zone)
    if ends_at <= starts_at: ends_at += timedelta(days=1)
    return starts_at, ends_at

def generate_roster(roster):
    """Transparent greedy generator; returns generated assignments and explicit gaps."""
    if roster.status != RosterVersion.DRAFT: raise ValueError(_("Only draft rosters can be generated."))
    roster.assignments.filter(source="generated").delete()
    templates = ShiftTemplate.objects.select_related("location").all()
    day = roster.month
    gaps = []
    created = 0
    with transaction.atomic():
        while day.month == roster.month.month:
            for template in templates:
                starts_at, ends_at = shift_datetimes(day, template)
                existing = roster.assignments.filter(location=template.location, starts_at=starts_at, ends_at=ends_at).count()
                # Cover the contractual minimum first. Preferences score the
                # eligible candidates, but a zero-score employee may still be
                # selected when coverage is otherwise short.
                for slot in range(max(template.max_headcount - existing, 0)):
                    candidates = []
                    for employee in Employee.objects.filter(active=True).prefetch_related("allowed_locations"):
                        valid, reason = eligible_for_shift(employee, template.location, starts_at, ends_at, roster)
                        if valid:
                            wishes = RosterWish.objects.filter(employee=employee, starts_on__lte=day, ends_on__gte=day)
                            score = 0
                            for wish in wishes:
                                weight = employee.wish_priority
                                if wish.preferred_location_id == template.location_id: score += weight
                                if day.weekday() in wish.preferred_weekdays: score += weight
                                elif wish.preferred_weekdays: score -= weight
                                # A wanted/unwanted date is a normal preference.  A desired
                                # day off is deliberately stronger, but remains a soft wish;
                                # only an approved absence makes the employee ineligible.
                                if wish.desired_day_off: score -= weight * 4
                                elif wish.date_preference == RosterWish.WANTED: score += weight * 2
                                elif wish.date_preference == RosterWish.UNWANTED: score -= weight * 2
                            candidates.append((score, -employee.pk, employee))
                    if candidates:
                        if existing + slot < template.min_headcount:
                            # Core staffing is based only on hard eligibility.
                            # Do not consume a positive wish merely to fill a
                            # required place when another eligible employee is
                            # available.
                            employee = min(candidates, key=lambda item: item[2].pk)[2]
                        else:
                            score, _, employee = max(candidates)
                            # Extra capacity is preference-led: without a
                            # positive wish, leave the optional place empty.
                            if score <= 0:
                                break
                        ShiftAssignment.objects.create(roster_version=roster, employee=employee, location=template.location, starts_at=starts_at, ends_at=ends_at, source="generated")
                        created += 1
                    else:
                        gaps.append({"date": day, "template": template, "reason": _("No active, eligible employee is available.")})
            day += timedelta(days=1)
    return created, gaps

def coverage_for_roster(roster):
    """Returns every required shift instance with staffing count and gap."""
    rows = []
    day = roster.month
    templates = ShiftTemplate.objects.select_related("location").all()
    while day.month == roster.month.month:
        for template in templates:
            starts_at, ends_at = shift_datetimes(day, template)
            assigned = roster.assignments.filter(location=template.location, starts_at=starts_at, ends_at=ends_at).select_related("employee")
            rows.append({"date": day, "template": template, "starts_at": starts_at, "ends_at": ends_at, "assignments": assigned, "minimum": template.min_headcount, "maximum": template.max_headcount, "gap": max(template.min_headcount - assigned.count(), 0)})
        day += timedelta(days=1)
    return rows

def roster_calendar(roster, proposal=None):
    """Build a Monday--Sunday month grid for a roster or its proposed result.

    A proposal replaces solver-owned assignments in its planning window, while
    manual and earlier assignments remain visible as fixed assignments.  Each
    shift therefore has both the displayed staffing and (for previews) its
    change from the current draft.
    """
    templates = list(ShiftTemplate.objects.select_related("location").all())
    current = list(roster.assignments.select_related("employee", "location").order_by("starts_at", "employee__name"))
    planning_starts_on = proposal.planning_starts_on if proposal else None
    if proposal:
        fixed = [row for row in current if row.source == "manual" or row.starts_at.date() < planning_starts_on]
        displayed = [*fixed, *list(proposal.proposed_assignments.select_related("employee", "location").order_by("starts_at", "employee__name"))]
    else:
        displayed = current

    def assignment_key(row):
        return row.location_id, row.starts_at, row.ends_at

    def employee_assignment_key(row):
        return row.employee_id, *assignment_key(row)

    current_by_shift = defaultdict(list)
    displayed_by_shift = defaultdict(list)
    for row in current:
        current_by_shift[assignment_key(row)].append(row)
    for row in displayed:
        displayed_by_shift[assignment_key(row)].append(row)
    current_assignment_keys = {employee_assignment_key(row) for row in current}
    displayed_assignment_keys = {employee_assignment_key(row) for row in displayed}

    def change_rows(rows, keys):
        return [row for row in rows if employee_assignment_key(row) in keys]

    added_keys = displayed_assignment_keys - current_assignment_keys
    removed_keys = current_assignment_keys - displayed_assignment_keys

    shifts_by_date = defaultdict(list)
    known_keys = set()
    day = roster.month
    while day.month == roster.month.month:
        for template in templates:
            starts_at, ends_at = shift_datetimes(day, template)
            key = (template.location_id, starts_at, ends_at)
            known_keys.add(key)
            assignments = displayed_by_shift[key]
            shifts_by_date[day].append({
                "template": template,
                "location": template.location,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "assignments": assignments,
                "added_assignments": change_rows(assignments, added_keys),
                "removed_assignments": change_rows(current_by_shift[key], removed_keys),
                "assigned_count": len(assignments),
                "previous_count": len(current_by_shift[key]),
                "delta": len(assignments) - len(current_by_shift[key]),
                "minimum": template.min_headcount,
                "maximum": template.max_headcount,
                "gap": max(template.min_headcount - len(assignments), 0),
                "is_custom": False,
            })
        day += timedelta(days=1)

    # Custom manual shifts are not tied to a template, but still belong in the
    # calendar rather than disappearing from the roster presentation.
    for key in set(current_by_shift) | set(displayed_by_shift):
        if key in known_keys:
            continue
        location_id, starts_at, ends_at = key
        date_key = starts_at.astimezone(ZoneInfo(settings.BUSINESS_TIME_ZONE)).date()
        if date_key.month != roster.month.month or date_key.year != roster.month.year:
            continue
        assignments = displayed_by_shift[key]
        location = (assignments or current_by_shift[key])[0].location
        shifts_by_date[date_key].append({
            "template": None,
            "location": location,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "assignments": assignments,
            "added_assignments": change_rows(assignments, added_keys),
            "removed_assignments": change_rows(current_by_shift[key], removed_keys),
            "assigned_count": len(assignments),
            "previous_count": len(current_by_shift[key]),
            "delta": len(assignments) - len(current_by_shift[key]),
            "minimum": None,
            "maximum": None,
            "gap": 0,
            "is_custom": True,
        })
    for shifts in shifts_by_date.values():
        shifts.sort(key=lambda shift: (shift["starts_at"], shift["location"].name))

    weeks = []
    for week in Calendar(firstweekday=0).monthdatescalendar(roster.month.year, roster.month.month):
        weeks.append([{
            "date": cell_date,
            "in_month": cell_date.month == roster.month.month and cell_date.year == roster.month.year,
            "is_weekend": cell_date.weekday() >= 5,
            "shifts": shifts_by_date[cell_date],
        } for cell_date in week])
    return weeks

def proposal_workload_delta(proposal):
    """Per-employee shift/day workload before and after applying a preview."""
    roster = proposal.roster_version
    current = list(roster.assignments.select_related("employee"))
    planning_starts_on = proposal.planning_starts_on or roster.month
    fixed = [row for row in current if row.source == "manual" or row.starts_at.date() < planning_starts_on]
    after = [*fixed, *list(proposal.proposed_assignments.select_related("employee"))]

    def workloads(assignments):
        values = defaultdict(lambda: {"shifts": 0, "days": set(), "employee": None})
        for row in assignments:
            item = values[row.employee_id]
            item["employee"] = row.employee
            item["shifts"] += 1
            item["days"].add(row.starts_at.astimezone(ZoneInfo(settings.BUSINESS_TIME_ZONE)).date())
        return values

    before, final = workloads(current), workloads(after)
    rows = []
    for employee_id in sorted(set(before) | set(final), key=lambda pk: str((final.get(pk) or before[pk])["employee"])):
        prior, result = before.get(employee_id), final.get(employee_id)
        rows.append({
            "employee": (result or prior)["employee"],
            "before_shifts": prior["shifts"] if prior else 0,
            "before_days": len(prior["days"]) if prior else 0,
            "after_shifts": result["shifts"] if result else 0,
            "after_days": len(result["days"]) if result else 0,
        })
    return rows

def absence_replacements(absence):
    impacted = ShiftAssignment.objects.filter(employee=absence.employee, starts_at__lt=absence.ends_at, ends_at__gt=absence.starts_at)
    proposals = []
    from apps.people.models import Employee
    for assignment in impacted:
        choices = []
        for candidate in Employee.objects.exclude(pk=absence.employee_id):
            valid, reason = eligible_for_shift(candidate, assignment.location, assignment.starts_at, assignment.ends_at)
            if valid: choices.append(candidate)
        proposals.append((assignment, choices))
    return proposals

def _overlaps(first_start, first_end, second_start, second_end):
    return first_start < second_end and first_end > second_start

def _wish_score(employee, location, day, wishes):
    score = 0
    for wish in wishes.get(employee.pk, []):
        if not (wish.starts_on <= day <= wish.ends_on):
            continue
        weight = employee.wish_priority
        if wish.preferred_location_id == location.pk: score += weight
        if day.weekday() in wish.preferred_weekdays: score += weight
        elif wish.preferred_weekdays: score -= weight
        if wish.desired_day_off: score -= weight * 4
        elif wish.date_preference == RosterWish.WANTED: score += weight * 2
        elif wish.date_preference == RosterWish.UNWANTED: score -= weight * 2
    return score

def roster_input_fingerprint(roster, planning_starts_on=None):
    """Stable snapshot of every input that can change a proposed allocation."""
    planning_start = planning_starts_on or roster.month
    retention_assignments = []
    if planning_start > roster.month:
        retention_assignments = list(roster.assignments.filter(source__in=["generated", "solver_generated"], starts_at__date__gte=planning_start).order_by("pk").values("id", "employee_id", "location_id", "starts_at", "ends_at", "source"))
    payload = {
        "templates": list(ShiftTemplate.objects.order_by("pk").values("id", "location_id", "start_time", "end_time", "min_headcount", "max_headcount")),
        "employees": list(Employee.objects.order_by("pk").values("id", "active", "wish_priority")),
        "eligibility": list(Employee.allowed_locations.through.objects.order_by("pk").values("employee_id", "location_id", "starts_on", "ends_on")),
        "planning_starts_on": str(planning_start),
        "fixed_assignments": list(roster.assignments.filter(models.Q(source="manual") | models.Q(starts_at__date__lt=planning_start)).order_by("pk").values("id", "employee_id", "location_id", "starts_at", "ends_at", "source", "override_reason")),
        # A partial preview also depends on the generated assignments it tries
        # to retain.  Include them so a changed draft cannot apply a stale
        # preview with an out-of-date retention baseline.
        "retention_assignments": retention_assignments,
        "absences": list(Absence.objects.filter(status=Absence.APPROVED).order_by("pk").values("employee_id", "starts_at", "ends_at")),
        "availability": list(Availability.objects.filter(available=False).order_by("pk").values("employee_id", "starts_at", "ends_at")),
        "wishes": list(RosterWish.objects.order_by("pk").values("employee_id", "starts_on", "ends_on", "preferred_location_id", "preferred_weekdays", "date_preference", "desired_day_off")),
        "employee_targets": list(roster.employee_targets.order_by("employee_id").values("employee_id", "target_shifts")),
    }
    return hashlib.sha256(json.dumps(payload, default=str, sort_keys=True).encode()).hexdigest()

class RosterOptimizationService:
    """CP-SAT roster optimizer with lexicographic operational objectives."""
    MAX_SECONDS = 20

    def __init__(self, roster, planning_starts_on=None):
        self.roster = roster
        self.planning_starts_on = planning_starts_on or roster.month
        self.templates = list(ShiftTemplate.objects.select_related("location").all())
        self.employees = list(Employee.objects.filter(active=True).prefetch_related("allowed_locations"))
        self.wishes = {}
        self.targets = dict(roster.employee_targets.values_list("employee_id", "target_shifts"))
        month_end = (roster.month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        for wish in RosterWish.objects.filter(starts_on__lte=month_end, ends_on__gte=roster.month):
            self.wishes.setdefault(wish.employee_id, []).append(wish)

    def _instances(self):
        rows, day = [], self.planning_starts_on
        while day.month == self.roster.month.month:
            for template in self.templates:
                starts_at, ends_at = shift_datetimes(day, template)
                rows.append({"template": template, "day": day, "starts_at": starts_at, "ends_at": ends_at})
            day += timedelta(days=1)
        return rows

    def _manual_validation(self, instances):
        from django.db.models import Q
        manual = list(self.roster.assignments.filter(Q(source="manual") | Q(starts_at__date__lt=self.planning_starts_on)).select_related("employee", "location"))
        issues = []
        for index, assignment in enumerate(manual):
            for other in manual[index + 1:]:
                if assignment.employee_id == other.employee_id and _overlaps(assignment.starts_at, assignment.ends_at, other.starts_at, other.ends_at):
                    issues.append(f"Manual assignments #{assignment.pk} and #{other.pk} overlap for {assignment.employee}.")
        for instance in instances:
            count = sum(a.location_id == instance["template"].location_id and a.starts_at == instance["starts_at"] and a.ends_at == instance["ends_at"] for a in manual)
            if count > instance["template"].max_headcount:
                issues.append(f"{instance['day']}: manual assignments exceed the maximum for {instance['template']}.")
        return manual, issues

    def create_preview(self):
        if self.roster.status != RosterVersion.DRAFT: raise ValueError("Only draft rosters can be optimized.")
        from ortools.sat.python import cp_model
        instances = self._instances()
        manual, issues = self._manual_validation(instances)
        if issues: raise ValueError("Manual assignments must be corrected before optimization: " + " ".join(issues))
        model = cp_model.CpModel()
        locked_by_instance = {index: [] for index in range(len(instances))}
        for index, instance in enumerate(instances):
            for assignment in manual:
                if assignment.location_id == instance["template"].location_id and assignment.starts_at == instance["starts_at"] and assignment.ends_at == instance["ends_at"]:
                    locked_by_instance[index].append(assignment)
        # When regenerating only part of a month, existing automatic shifts in
        # that window are a soft baseline. They remain variables (so absences,
        # availability, and coverage can still require changes), but retaining
        # them is optimized ahead of balancing and wishes.
        existing_by_instance = {index: set() for index in range(len(instances))}
        if self.planning_starts_on > self.roster.month:
            existing_automatic = list(self.roster.assignments.filter(source__in=["generated", "solver_generated"], starts_at__date__gte=self.planning_starts_on))
            for index, instance in enumerate(instances):
                existing_by_instance[index] = {
                    assignment.employee_id for assignment in existing_automatic
                    if assignment.location_id == instance["template"].location_id
                    and assignment.starts_at == instance["starts_at"]
                    and assignment.ends_at == instance["ends_at"]
                }
        variables, candidates = {}, {}
        for index, instance in enumerate(instances):
            for employee in self.employees:
                if any(a.employee_id == employee.pk for a in locked_by_instance[index]): continue
                if any(a.employee_id == employee.pk and _overlaps(a.starts_at, a.ends_at, instance["starts_at"], instance["ends_at"]) for a in manual): continue
                valid, _ = eligible_for_shift(employee, instance["template"].location, instance["starts_at"], instance["ends_at"], self.roster, assignment_sources=["manual"])
                if valid:
                    variable = model.NewBoolVar(f"e{employee.pk}_s{index}")
                    variables[(employee.pk, index)] = variable
                    candidates.setdefault(index, []).append(employee)
        for index, instance in enumerate(instances):
            instance_vars = [variable for (employee_id, slot), variable in variables.items() if slot == index]
            model.Add(sum(instance_vars) + len(locked_by_instance[index]) <= instance["template"].max_headcount)
        for employee in self.employees:
            employee_vars = [(index, variable) for (employee_id, index), variable in variables.items() if employee_id == employee.pk]
            for left in range(len(employee_vars)):
                for right in range(left + 1, len(employee_vars)):
                    first, second = instances[employee_vars[left][0]], instances[employee_vars[right][0]]
                    if _overlaps(first["starts_at"], first["ends_at"], second["starts_at"], second["ends_at"]): model.Add(employee_vars[left][1] + employee_vars[right][1] <= 1)
        coverage = []
        for index, instance in enumerate(instances):
            covered = model.NewIntVar(0, instance["template"].min_headcount, f"coverage_{index}")
            vars_for_instance = [variable for (employee_id, slot), variable in variables.items() if slot == index]
            model.Add(covered <= sum(vars_for_instance) + len(locked_by_instance[index]))
            coverage.append(covered)
        total_assignments = sum(variables.values()) + len(manual)
        eligible_employees = [employee for employee in self.employees if any(employee.pk == employee_id for employee_id, index in variables) or any(assignment.employee_id == employee.pk for assignment in manual)]
        loads = []
        for employee in eligible_employees:
            count = sum(1 for assignment in manual if assignment.employee_id == employee.pk)
            loads.append(model.NewIntVar(count, len(instances) + count, f"load_{employee.pk}"))
            model.Add(loads[-1] == count + sum(variable for (employee_id, index), variable in variables.items() if employee_id == employee.pk))
        span = model.NewIntVar(0, len(instances), "workload_span")
        if loads: model.AddMaxEquality(span, loads); minimum_load = model.NewIntVar(0, len(instances), "minimum_load"); model.AddMinEquality(minimum_load, loads)
        else: minimum_load = 0
        target_fulfillment = []
        for employee, load in zip(eligible_employees, loads):
            if employee.pk not in self.targets:
                continue
            target = self.targets[employee.pk]
            fulfilled = model.NewIntVar(0, target, f"target_fulfilled_{employee.pk}")
            model.AddMinEquality(fulfilled, [load, target])
            target_fulfillment.append(fulfilled)
        wish_total = sum(_wish_score(employee, instances[index]["template"].location, instances[index]["day"], self.wishes) * variable for (employee_id, index), variable in variables.items() for employee in self.employees if employee.pk == employee_id)
        solver = cp_model.CpSolver(); solver.parameters.max_time_in_seconds = self.MAX_SECONDS; solver.parameters.num_search_workers = 8
        def optimize(expression, maximize=True):
            model.Maximize(expression) if maximize else model.Minimize(expression)
            status = solver.Solve(model)
            if status != cp_model.OPTIMAL: raise ValueError(_("Roster optimizer could not prove an optimal result within 20 seconds. Reduce the planning scope and retry."))
            return int(solver.Value(expression))
        coverage_value = optimize(sum(coverage))
        model.Add(sum(coverage) == coverage_value)
        target_value = 0
        if target_fulfillment:
            target_value = optimize(sum(target_fulfillment))
            model.Add(sum(target_fulfillment) == target_value)
        # With targets configured, do not keep filling optional capacity after
        # coverage and targets are met. This keeps MAX as a ceiling, not a
        # staffing goal. Rosters without targets retain the prior behavior of
        # filling all feasible capacity.
        assignments_value = optimize(total_assignments, maximize=not bool(target_fulfillment))
        model.Add(total_assignments == assignments_value)
        retained_value = 0
        if self.planning_starts_on > self.roster.month:
            retained_assignments = sum(
                variable for (employee_id, index), variable in variables.items()
                if employee_id in existing_by_instance[index]
            )
            retained_value = optimize(retained_assignments)
            model.Add(retained_assignments == retained_value)
        if loads:
            # Span is max(load); constrain the minimum separately to measure max-min.
            model.AddMinEquality(minimum_load, loads)
            imbalance = model.NewIntVar(0, len(instances), "imbalance")
            model.Add(imbalance == span - minimum_load)
            imbalance_value = optimize(imbalance, maximize=False)
            model.Add(imbalance == imbalance_value)
        else: imbalance_value = 0
        wish_value = optimize(wish_total)
        proposal = RosterGenerationRun.objects.create(roster_version=self.roster, planning_starts_on=self.planning_starts_on, input_fingerprint=roster_input_fingerprint(self.roster, self.planning_starts_on), summary={"minimum_coverage": coverage_value, "target_fulfillment": target_value, "assignments": assignments_value, "retained_assignments": retained_value, "workload_span": imbalance_value, "wish_score": wish_value})
        proposal_rows, diagnostics, workload = [], [], {}
        for index, instance in enumerate(instances):
            assigned_count = len(locked_by_instance[index])
            for employee in candidates.get(index, []):
                variable = variables[(employee.pk, index)]
                if solver.Value(variable):
                    score = _wish_score(employee, instance["template"].location, instance["day"], self.wishes)
                    proposal_rows.append(RosterGenerationProposalAssignment(generation_run=proposal, employee=employee, location=instance["template"].location, starts_at=instance["starts_at"], ends_at=instance["ends_at"], wish_score=score))
                    assigned_count += 1; workload[employee.name] = workload.get(employee.name, 0) + 1
            if assigned_count < instance["template"].min_headcount:
                diagnostics.append({"date": instance["day"].isoformat(), "shift": instance["template"].name, "location": instance["template"].location.name, "minimum": instance["template"].min_headcount, "assigned": assigned_count, "eligible_candidates": len(candidates.get(index, [])), "reason": _("Not enough eligible employees after absences, unavailability, overlaps, and locked assignments.")})
        RosterGenerationProposalAssignment.objects.bulk_create(proposal_rows)
        weekday_preferences = {}
        for assignment in [*manual, *proposal_rows]:
            employee_wishes = self.wishes.get(assignment.employee_id, [])
            local_day = assignment.starts_at.astimezone(ZoneInfo(settings.BUSINESS_TIME_ZONE)).date()
            for wish in employee_wishes:
                if not wish.preferred_weekdays or not (wish.starts_on <= local_day <= wish.ends_on):
                    continue
                item = weekday_preferences.setdefault(assignment.employee_id, {"employee": assignment.employee.name, "preferred": 0, "non_preferred": 0})
                if local_day.weekday() in wish.preferred_weekdays: item["preferred"] += 1
                else: item["non_preferred"] += 1
        proposal.summary["workload"] = workload
        proposal.summary["proposed_assignments"] = len(proposal_rows)
        proposal.summary["weekday_preferences"] = list(weekday_preferences.values())
        proposal.diagnostics = diagnostics
        proposal.save(update_fields=["summary", "diagnostics"])
        return proposal

    @staticmethod
    def apply_preview(proposal):
        from django.utils import timezone
        if proposal.status != RosterGenerationRun.PREVIEW: raise ValueError(_("This proposal is no longer available to apply."))
        planning_starts_on = proposal.planning_starts_on or proposal.roster_version.month
        if proposal.input_fingerprint != roster_input_fingerprint(proposal.roster_version, planning_starts_on): raise ValueError(_("The roster inputs changed after this preview. Generate a new preview."))
        with transaction.atomic():
            proposal.roster_version.assignments.filter(source__in=["generated", "solver_generated"], starts_at__date__gte=planning_starts_on).delete()
            ShiftAssignment.objects.bulk_create([ShiftAssignment(roster_version=proposal.roster_version, employee=row.employee, location=row.location, starts_at=row.starts_at, ends_at=row.ends_at, source="solver_generated") for row in proposal.proposed_assignments.select_related("employee", "location")])
            proposal.status = RosterGenerationRun.APPLIED; proposal.applied_at = timezone.now(); proposal.save(update_fields=["status", "applied_at"])

def proposal_delta(proposal):
    """Describe the assignment changes that applying a preview would make."""
    roster = proposal.roster_version
    current = list(roster.assignments.select_related("employee", "location"))
    planning_starts_on = proposal.planning_starts_on or roster.month
    manual = [assignment for assignment in current if assignment.source == "manual" or assignment.starts_at.date() < planning_starts_on]
    proposed = list(proposal.proposed_assignments.select_related("employee", "location"))
    def key(row): return (row.employee_id, row.location_id, row.starts_at, row.ends_at)
    current_by_key = {key(row): row for row in current}
    proposed_by_key = {key(row): row for row in [*manual, *proposed]}
    rows = []
    for assignment_key in sorted(proposed_by_key.keys() - current_by_key.keys(), key=lambda item: (item[2], item[0])):
        assignment = proposed_by_key[assignment_key]
        rows.append({"change": "added", "assignment": assignment})
    for assignment_key in sorted(current_by_key.keys() - proposed_by_key.keys(), key=lambda item: (item[2], item[0])):
        assignment = current_by_key[assignment_key]
        rows.append({"change": "removed", "assignment": assignment})
    return rows
