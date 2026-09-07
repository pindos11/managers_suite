from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from apps.people.models import Employee
from .forms import AbsenceForm, AvailabilityForm, AvailabilityUploadForm, GenerationRequestForm, LegacyRosterImportForm, MonthlyShiftTargetForm, RosterCreateForm, RosterWishForm, ShiftAssignmentForm, ShiftTemplateForm
from .models import Absence, Availability, RosterEmployeeTarget, RosterGenerationRun, RosterVersion, RosterWish, ShiftAssignment, ShiftTemplate
from .services import RosterOptimizationService, absence_replacements, coverage_for_roster, eligible_for_shift, generate_roster, proposal_delta, proposal_workload_delta, roster_calendar, shift_datetimes
from .exports import excel_export, pdf_export

@login_required
def rosters(request):
    return render(request, "roster/rosters.html", {"rosters": RosterVersion.objects.prefetch_related("assignments").all()})

@login_required
def roster_create(request):
    form = RosterCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        roster = form.save(); messages.success(request, _("Draft roster created. Add shift templates, then generate assignments."))
        return redirect("roster_detail", pk=roster.pk)
    return render(request, "form.html", {"form": form, "title": _("Create monthly roster")})

@login_required
def roster_detail(request, pk):
    roster = get_object_or_404(RosterVersion, pk=pk)
    return render(request, "roster/detail.html", {"roster": roster, "calendar_weeks": roster_calendar(roster), "generation_form": GenerationRequestForm(roster), "target_form": MonthlyShiftTargetForm(roster), "saved_targets": roster.employee_targets.select_related("employee").order_by("employee__name")})

@login_required
def roster_targets(request, pk):
    roster = get_object_or_404(RosterVersion, pk=pk, status=RosterVersion.DRAFT)
    form = MonthlyShiftTargetForm(roster, request.POST or None)
    if request.method == "POST" and form.is_valid():
        target_ids = set()
        for name, target in form.cleaned_data.items():
            employee_id = int(name.removeprefix("employee_"))
            if target is None:
                continue
            target_ids.add(employee_id)
            RosterEmployeeTarget.objects.update_or_create(roster_version=roster, employee_id=employee_id, defaults={"target_shifts": target})
        roster.employee_targets.exclude(employee_id__in=target_ids).delete()
        messages.success(request, _("Monthly shift targets saved."))
    return redirect("roster_detail", pk=roster.pk)

def _legacy_import_assignments(roster, template, matrix):
    import csv
    from io import StringIO

    rows = [row for row in csv.reader(StringIO(matrix), delimiter="\t") if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise ValidationError(_("Paste a header row and at least one employee row."))
    days = {}
    for column, value in enumerate(rows[0][1:], start=1):
        value = value.strip()
        if not value:
            continue
        try:
            day = int(value)
        except ValueError:
            raise ValidationError(_("Column %(column)s has '%(value)s'. Day headers must be numbers within this roster month.") % {"column": column + 1, "value": value})
        month_end = (roster.month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if not 1 <= day <= month_end.day:
            raise ValidationError(_("Day %(day)s is outside this roster month.") % {"day": day})
        if day in days.values():
            raise ValidationError(_("Day %(day)s appears more than once in the pasted header.") % {"day": day})
        days[column] = day
    if not days:
        raise ValidationError(_("Add day numbers to the first pasted row."))
    employees = {}
    for employee in Employee.objects.filter(active=True):
        employees.setdefault(employee.name.strip().casefold(), []).append(employee)
    assignments, skipped_names, seen, capacity = [], [], set(), {}
    for row_number, row in enumerate(rows[1:], start=2):
        name = row[0].strip() if row else ""
        if not name:
            continue
        matches = employees.get(name.casefold(), [])
        if not matches:
            skipped_names.append(name)
            continue
        if len(matches) != 1:
            raise ValidationError(_("Employee '%(name)s' is ambiguous. Use unique employee names before importing.") % {"name": name})
        employee = matches[0]
        for column, day in days.items():
            if column >= len(row) or not row[column].strip():
                continue
            starts_at, ends_at = shift_datetimes(roster.month.replace(day=day), template)
            key = (employee.pk, starts_at, ends_at)
            if key in seen:
                raise ValidationError(_("%(name)s is marked more than once for day %(day)s.") % {"name": name, "day": day})
            seen.add(key)
            if ShiftAssignment.objects.filter(roster_version=roster, employee=employee, starts_at=starts_at, ends_at=ends_at).exists():
                raise ValidationError(_("%(name)s already has this shift on day %(day)s.") % {"name": name, "day": day})
            valid, reason = eligible_for_shift(employee, template.location, starts_at, ends_at, roster)
            if not valid:
                raise ValidationError(_("%(name)s cannot be assigned on day %(day)s: %(reason)s.") % {"name": name, "day": day, "reason": reason})
            capacity[(starts_at, ends_at)] = capacity.get((starts_at, ends_at), 0) + 1
            assignments.append(ShiftAssignment(roster_version=roster, employee=employee, location=template.location, starts_at=starts_at, ends_at=ends_at, source="manual", override_reason=_("Imported from legacy roster.")))
    if not assignments:
        raise ValidationError(_("The pasted roster has no filled day cells to import."))
    for (starts_at, ends_at), count in capacity.items():
        existing = ShiftAssignment.objects.filter(roster_version=roster, location=template.location, starts_at=starts_at, ends_at=ends_at).count()
        if existing + count > template.max_headcount:
            raise ValidationError(_("The imported employees exceed the maximum staff for %(date)s.") % {"date": timezone.localtime(starts_at).date()})
    return assignments, skipped_names

@login_required
def roster_import(request, pk):
    roster = get_object_or_404(RosterVersion, pk=pk, status=RosterVersion.DRAFT)
    form = LegacyRosterImportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            assignments, skipped_names = _legacy_import_assignments(roster, form.cleaned_data["template"], form.cleaned_data["matrix"])
        except ValidationError as error:
            form.add_error("matrix", error)
        else:
            with transaction.atomic():
                ShiftAssignment.objects.bulk_create(assignments)
            messages.success(request, _("Imported %(count)s legacy roster assignment(s).") % {"count": len(assignments)})
            if skipped_names:
                messages.warning(request, _("Ignored %(count)s row(s) for employees not in the current roster: %(names)s.") % {"count": len(skipped_names), "names": ", ".join(skipped_names)})
            return redirect("roster_detail", pk=roster.pk)
    return render(request, "roster/import.html", {"roster": roster, "form": form})

@login_required
def roster_delete(request, pk):
    roster = get_object_or_404(RosterVersion, pk=pk)
    if request.method == "POST":
        roster.delete()
        messages.success(request, _("Roster deleted."))
        return redirect("rosters")
    return render(request, "roster/delete.html", {"roster": roster})

@login_required
def roster_export(request, pk):
    roster = get_object_or_404(RosterVersion, pk=pk, status__in=[RosterVersion.DRAFT, RosterVersion.PUBLISHED])
    export_format = request.GET.get("format")
    scope = request.GET.get("scope", "total")
    if export_format not in {"xlsx", "pdf"}:
        return render(request, "roster/export.html", {"roster": roster})
    if scope not in {"total", "employee_pages"}:
        return HttpResponse("Invalid export scope.", status=400)
    content = excel_export(roster, scope) if export_format == "xlsx" else pdf_export(roster, scope)
    extension = "xlsx" if export_format == "xlsx" else "pdf"
    response = HttpResponse(content, content_type={"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "pdf": "application/pdf"}[extension])
    response["Content-Disposition"] = f'attachment; filename="roster-{roster.month:%Y-%m}-{scope}.{extension}"'
    return response

@login_required
def generate(request, pk):
    roster = get_object_or_404(RosterVersion, pk=pk)
    if request.method == "POST":
        form = GenerationRequestForm(roster, request.POST)
        if form.is_valid():
            try:
                proposal = RosterOptimizationService(roster, form.cleaned_data["starts_on"]).create_preview()
                return redirect("roster_proposal", pk=roster.pk, run_pk=proposal.pk)
            except ValueError as error: messages.error(request, str(error))
        else: messages.error(request, _("Choose a valid start date for the planning window."))
    return redirect("roster_detail", pk=pk)

@login_required
def proposal(request, pk, run_pk):
    roster = get_object_or_404(RosterVersion, pk=pk)
    run = get_object_or_404(RosterGenerationRun.objects.prefetch_related("proposed_assignments__employee", "proposed_assignments__location"), pk=run_pk, roster_version=roster)
    return render(request, "roster/proposal.html", {"roster": roster, "run": run, "calendar_weeks": roster_calendar(roster, run), "delta": proposal_delta(run), "workload_delta": proposal_workload_delta(run)})

@login_required
def proposal_apply(request, pk, run_pk):
    roster = get_object_or_404(RosterVersion, pk=pk, status=RosterVersion.DRAFT)
    run = get_object_or_404(RosterGenerationRun, pk=run_pk, roster_version=roster)
    if request.method == "POST":
        try:
            RosterOptimizationService.apply_preview(run)
            messages.success(request, _("Solver proposal applied. Manual assignments were kept."))
            return redirect("roster_detail", pk=roster.pk)
        except ValueError as error: messages.error(request, str(error))
    return redirect("roster_proposal", pk=roster.pk, run_pk=run.pk)

@login_required
def assignment_create(request, roster_pk):
    roster = get_object_or_404(RosterVersion, pk=roster_pk, status=RosterVersion.DRAFT)
    initial = {}
    template = None
    if request.GET.get("template") and request.GET.get("date"):
        template = get_object_or_404(ShiftTemplate, pk=request.GET["template"])
        from datetime import date
        starts_at, ends_at = shift_datetimes(date.fromisoformat(request.GET["date"]), template)
        initial.update({"location": template.location_id, "starts_at": starts_at, "ends_at": ends_at})
    if request.method != "POST":
        for field in ("location", "starts_at", "ends_at"):
            if request.GET.get(field): initial[field] = request.GET[field]
    data = request.POST or None
    if template and request.method == "POST":
        # The calendar action owns these values; do not let a hidden form
        # field turn an "add employee" operation into a different shift.
        data = request.POST.copy()
        data.update({"location": str(template.location_id), "starts_at": starts_at.strftime("%Y-%m-%dT%H:%M"), "ends_at": ends_at.strftime("%Y-%m-%dT%H:%M")})
    form = ShiftAssignmentForm(data, initial=initial, inherited_shift=bool(template))
    if request.method == "POST" and form.is_valid():
        employees = form.cleaned_data["employee"]
        location = form.cleaned_data["location"]
        starts_at = form.cleaned_data["starts_at"]
        ends_at = form.cleaned_data["ends_at"]
        override_reason = form.cleaned_data["override_reason"]
        duplicates = ShiftAssignment.objects.filter(roster_version=roster, employee__in=employees, starts_at=starts_at, ends_at=ends_at)
        conflicts = [employee for employee in employees if not eligible_for_shift(employee, location, starts_at, ends_at, roster)[0]]
        assigned_count = ShiftAssignment.objects.filter(roster_version=roster, location=location, starts_at=starts_at, ends_at=ends_at).count()
        if template and assigned_count + len(employees) > template.max_headcount:
            form.add_error("employee", _("Only %(count)s more employee(s) can be added to this shift.") % {"count": max(0, template.max_headcount - assigned_count)})
        elif duplicates.exists():
            form.add_error("employee", _("One or more selected employees are already assigned to this shift. Remove the existing assignment instead of adding a duplicate."))
        elif conflicts and not override_reason:
            form.add_error("override_reason", _("Conflict for %(employees)s. Explain this override.") % {"employees": ", ".join(str(employee) for employee in conflicts)})
        else:
            ShiftAssignment.objects.bulk_create([
                ShiftAssignment(roster_version=roster, employee=employee, location=location, starts_at=starts_at, ends_at=ends_at, override_reason=override_reason, source="manual")
                for employee in employees
            ])
            messages.success(request, _("Shift assignments saved.")); return redirect("roster_detail", pk=roster.pk)
    return render(request, "roster/assignment_form.html", {"form": form, "roster": roster, "template": template, "starts_at": initial.get("starts_at"), "ends_at": initial.get("ends_at")})

@login_required
def assignment_delete(request, pk):
    assignment = get_object_or_404(ShiftAssignment, pk=pk, roster_version__status=RosterVersion.DRAFT); roster_pk = assignment.roster_version_id
    if request.method == "POST": assignment.delete(); messages.success(request, _("Shift assignment removed.")); return redirect("roster_detail", pk=roster_pk)
    return render(request, "roster/assignment_delete.html", {"assignment": assignment})

@login_required
def publish(request, pk):
    roster = get_object_or_404(RosterVersion, pk=pk); gaps = [row for row in coverage_for_roster(roster) if row["gap"]]
    if request.method == "POST":
        if gaps and not request.POST.get("accept_gaps"): messages.error(request, _("Confirm uncovered shifts before publishing."))
        else:
            RosterVersion.objects.filter(month=roster.month, status=RosterVersion.PUBLISHED).exclude(pk=roster.pk).update(status=RosterVersion.SUPERSEDED)
            roster.status = RosterVersion.PUBLISHED; roster.published_at = timezone.now(); roster.save(); messages.success(request, _("Roster published."))
            return redirect("roster_detail", pk=pk)
    return render(request, "roster/publish.html", {"roster": roster, "gaps": gaps})

@login_required
def unpublish(request, pk):
    roster = get_object_or_404(RosterVersion, pk=pk, status=RosterVersion.PUBLISHED)
    if request.method == "POST":
        roster.status = RosterVersion.DRAFT
        roster.published_at = None
        roster.save(update_fields=["status", "published_at"])
        messages.success(request, _("Roster returned to draft. Existing assignments were kept."))
        return redirect("roster_detail", pk=pk)
    return render(request, "roster/unpublish.html", {"roster": roster})

@login_required
def templates(request): return render(request, "roster/templates.html", {"templates": ShiftTemplate.objects.select_related("location").all()})

@login_required
def template_edit(request, pk=None):
    form = ShiftTemplateForm(request.POST or None, instance=get_object_or_404(ShiftTemplate, pk=pk) if pk else None)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, _("Shift template saved.")); return redirect("shift_templates")
    return render(request, "form.html", {"form": form, "title": _("Shift template")})

@login_required
def absences(request): return render(request, "roster/absences.html", {"absences": Absence.objects.select_related("employee").all()})

@login_required
def absence_edit(request, pk=None):
    form = AbsenceForm(request.POST or None, instance=get_object_or_404(Absence, pk=pk) if pk else None)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, _("Absence saved.")); return redirect("absences")
    return render(request, "form.html", {"form": form, "title": _("Absence")})

@login_required
def absence_proposal(request, pk):
    absence = get_object_or_404(Absence, pk=pk)
    return render(request, "roster/absence_proposal.html", {"absence": absence, "proposals": absence_replacements(absence)})

@login_required
def availability(request): return render(request, "roster/availability.html", {"records": Availability.objects.select_related("employee").all()})

@login_required
def availability_upload(request):
    form = AvailabilityUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data = form.import_data
        month_start = data["month"]
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        zone = ZoneInfo(settings.BUSINESS_TIME_ZONE)
        starts_at = datetime.combine(month_start, time.min, tzinfo=zone)
        ends_at = datetime.combine(next_month, time.min, tzinfo=zone)
        existing = Availability.objects.filter(employee=data["employee"], starts_at__lt=ends_at, ends_at__gt=starts_at)
        with transaction.atomic():
            # Retain portions of a manually entered period outside the imported
            # month, while replacing every availability day inside the month.
            for record in existing:
                original_end = record.ends_at
                before_month = record.starts_at < starts_at
                after_month = original_end > ends_at
                if before_month and after_month:
                    Availability.objects.create(employee=record.employee, starts_at=ends_at, ends_at=original_end, available=record.available, source=record.source, notes=record.notes)
                    record.ends_at = starts_at
                    record.save(update_fields=["ends_at"])
                elif before_month:
                    record.ends_at = starts_at
                    record.save(update_fields=["ends_at"])
                elif after_month:
                    record.starts_at = ends_at
                    record.save(update_fields=["starts_at"])
                else:
                    record.delete()
            days = (next_month - month_start).days
            Availability.objects.bulk_create([
                Availability(
                    employee=data["employee"],
                    starts_at=datetime.combine(month_start + timedelta(days=offset), time.min, tzinfo=zone),
                    ends_at=datetime.combine(month_start + timedelta(days=offset + 1), time.min, tzinfo=zone),
                    available=(month_start + timedelta(days=offset)) in data["selected_dates"],
                    source="dates_chooser_json",
                )
                for offset in range(days)
            ])
        messages.success(request, _("Imported availability for %(employee)s for %(month)s.") % {"employee": data["employee"], "month": month_start.strftime("%B %Y")})
        return redirect("availability")
    return render(request, "form.html", {"form": form, "title": _("Upload availability JSON")})

@login_required
def availability_edit(request, pk=None):
    record = get_object_or_404(Availability, pk=pk) if pk else None
    form = AvailabilityForm(request.POST or None, instance=record)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, _("Availability record saved.")); return redirect("availability")
    return render(request, "form.html", {"form": form, "title": _("Availability")})

@login_required
def availability_delete(request, pk):
    record = get_object_or_404(Availability, pk=pk)
    if request.method == "POST":
        record.delete()
        messages.success(request, _("Availability record removed."))
        return redirect("availability")
    return render(request, "roster/availability_delete.html", {"record": record})

@login_required
def wishes(request):
    return render(request, "roster/wishes.html", {"wishes": RosterWish.objects.select_related("employee", "preferred_location").all()})

@login_required
def wish_edit(request, pk=None):
    form = RosterWishForm(request.POST or None, instance=get_object_or_404(RosterWish, pk=pk) if pk else None)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, _("Roster wish saved.")); return redirect("roster_wishes")
    return render(request, "form.html", {"form": form, "title": _("Roster wish")})
