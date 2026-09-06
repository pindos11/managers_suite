from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from .forms import AbsenceForm, AvailabilityForm, GenerationRequestForm, MonthlyShiftTargetForm, RosterCreateForm, RosterWishForm, ShiftAssignmentForm, ShiftTemplateForm
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
    return render(request, "roster/detail.html", {"roster": roster, "calendar_weeks": roster_calendar(roster), "generation_form": GenerationRequestForm(roster), "target_form": MonthlyShiftTargetForm(roster)})

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
