from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from .forms import AbsenceForm, AvailabilityForm, GenerationRequestForm, RosterCreateForm, RosterWishForm, ShiftAssignmentForm, ShiftTemplateForm
from .models import Absence, Availability, RosterGenerationRun, RosterVersion, RosterWish, ShiftAssignment, ShiftTemplate
from .services import RosterOptimizationService, absence_replacements, coverage_for_roster, eligible_for_shift, generate_roster, proposal_delta, proposal_workload_delta, roster_calendar, shift_datetimes

@login_required
def rosters(request):
    return render(request, "roster/rosters.html", {"rosters": RosterVersion.objects.prefetch_related("assignments").all()})

@login_required
def roster_create(request):
    form = RosterCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        roster = form.save(); messages.success(request, "Draft roster created. Add shift templates, then generate assignments.")
        return redirect("roster_detail", pk=roster.pk)
    return render(request, "form.html", {"form": form, "title": "Create monthly roster"})

@login_required
def roster_detail(request, pk):
    roster = get_object_or_404(RosterVersion, pk=pk)
    return render(request, "roster/detail.html", {"roster": roster, "calendar_weeks": roster_calendar(roster), "generation_form": GenerationRequestForm(roster)})

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
        else: messages.error(request, "Choose a valid start date for the planning window.")
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
            messages.success(request, "Solver proposal applied. Manual assignments were kept.")
            return redirect("roster_detail", pk=roster.pk)
        except ValueError as error: messages.error(request, str(error))
    return redirect("roster_proposal", pk=roster.pk, run_pk=run.pk)

@login_required
def assignment_create(request, roster_pk):
    roster = get_object_or_404(RosterVersion, pk=roster_pk, status=RosterVersion.DRAFT)
    initial = {}
    if request.method != "POST":
        if request.GET.get("template") and request.GET.get("date"):
            template = get_object_or_404(ShiftTemplate, pk=request.GET["template"])
            from datetime import date
            starts_at, ends_at = shift_datetimes(date.fromisoformat(request.GET["date"]), template)
            initial.update({"location": template.location_id, "starts_at": starts_at, "ends_at": ends_at})
        for field in ("location", "starts_at", "ends_at"):
            if request.GET.get(field): initial[field] = request.GET[field]
    form = ShiftAssignmentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        assignment = form.save(commit=False); assignment.roster_version = roster; assignment.source = "manual"
        duplicate = ShiftAssignment.objects.filter(roster_version=roster, employee=assignment.employee, starts_at=assignment.starts_at, ends_at=assignment.ends_at).exists()
        valid, reason = eligible_for_shift(assignment.employee, assignment.location, assignment.starts_at, assignment.ends_at, roster)
        if duplicate:
            form.add_error("employee", "This employee is already assigned to this shift. Remove the existing assignment instead of adding a duplicate.")
        elif not valid and not assignment.override_reason: form.add_error("override_reason", f"Conflict: {reason}. Explain this override.")
        else:
            assignment.save(); messages.success(request, "Shift assignment saved."); return redirect("roster_detail", pk=roster.pk)
    return render(request, "roster/assignment_form.html", {"form": form, "roster": roster})

@login_required
def assignment_delete(request, pk):
    assignment = get_object_or_404(ShiftAssignment, pk=pk, roster_version__status=RosterVersion.DRAFT); roster_pk = assignment.roster_version_id
    if request.method == "POST": assignment.delete(); messages.success(request, "Shift assignment removed."); return redirect("roster_detail", pk=roster_pk)
    return render(request, "roster/assignment_delete.html", {"assignment": assignment})

@login_required
def publish(request, pk):
    roster = get_object_or_404(RosterVersion, pk=pk); gaps = [row for row in coverage_for_roster(roster) if row["gap"]]
    if request.method == "POST":
        if gaps and not request.POST.get("accept_gaps"): messages.error(request, "Confirm uncovered shifts before publishing.")
        else:
            RosterVersion.objects.filter(month=roster.month, status=RosterVersion.PUBLISHED).exclude(pk=roster.pk).update(status=RosterVersion.SUPERSEDED)
            roster.status = RosterVersion.PUBLISHED; roster.published_at = timezone.now(); roster.save(); messages.success(request, "Roster published.")
            return redirect("roster_detail", pk=pk)
    return render(request, "roster/publish.html", {"roster": roster, "gaps": gaps})

@login_required
def unpublish(request, pk):
    roster = get_object_or_404(RosterVersion, pk=pk, status=RosterVersion.PUBLISHED)
    if request.method == "POST":
        roster.status = RosterVersion.DRAFT
        roster.published_at = None
        roster.save(update_fields=["status", "published_at"])
        messages.success(request, "Roster returned to draft. Existing assignments were kept.")
        return redirect("roster_detail", pk=pk)
    return render(request, "roster/unpublish.html", {"roster": roster})

@login_required
def templates(request): return render(request, "roster/templates.html", {"templates": ShiftTemplate.objects.select_related("location").all()})

@login_required
def template_edit(request, pk=None):
    form = ShiftTemplateForm(request.POST or None, instance=get_object_or_404(ShiftTemplate, pk=pk) if pk else None)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, "Shift template saved."); return redirect("shift_templates")
    return render(request, "form.html", {"form": form, "title": "Shift template"})

@login_required
def absences(request): return render(request, "roster/absences.html", {"absences": Absence.objects.select_related("employee").all()})

@login_required
def absence_edit(request, pk=None):
    form = AbsenceForm(request.POST or None, instance=get_object_or_404(Absence, pk=pk) if pk else None)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, "Absence saved."); return redirect("absences")
    return render(request, "form.html", {"form": form, "title": "Absence"})

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
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, "Availability record saved."); return redirect("availability")
    return render(request, "form.html", {"form": form, "title": "Availability"})

@login_required
def availability_delete(request, pk):
    record = get_object_or_404(Availability, pk=pk)
    if request.method == "POST":
        record.delete()
        messages.success(request, "Availability record removed.")
        return redirect("availability")
    return render(request, "roster/availability_delete.html", {"record": record})

@login_required
def wishes(request):
    return render(request, "roster/wishes.html", {"wishes": RosterWish.objects.select_related("employee", "preferred_location").all()})

@login_required
def wish_edit(request, pk=None):
    form = RosterWishForm(request.POST or None, instance=get_object_or_404(RosterWish, pk=pk) if pk else None)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, "Roster wish saved."); return redirect("roster_wishes")
    return render(request, "form.html", {"form": form, "title": "Roster wish"})
