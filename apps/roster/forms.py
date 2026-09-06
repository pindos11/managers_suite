from django import forms
from datetime import timedelta
from django.utils.translation import gettext_lazy as _
from apps.people.models import Employee, Location
from .models import Absence, Availability, RosterVersion, RosterWish, ShiftAssignment, ShiftTemplate

class MonthInput(forms.DateInput):
    input_type = "month"

    def __init__(self, attrs=None):
        # Native month controls only accept an ISO year-month value, regardless
        # of the active display locale.
        super().__init__(attrs=attrs, format="%Y-%m")


class ISODateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None):
        # Native date controls only accept YYYY-MM-DD.  Letting Django select
        # a localized output format makes browsers clear the value (notably
        # when switching to Russian).
        super().__init__(attrs=attrs, format="%Y-%m-%d")

class RosterCreateForm(forms.ModelForm):
    # A native month input submits YYYY-MM rather than a full ISO date.
    # Declare the field explicitly because ModelForm Meta does not apply
    # input_formats to its generated DateField.
    month = forms.DateField(input_formats=["%Y-%m", "%Y-%m-%d"], widget=MonthInput())

    class Meta:
        model = RosterVersion
        fields = ["month"]

    def clean_month(self):
        month = self.cleaned_data["month"]
        return month.replace(day=1)

class ShiftTemplateForm(forms.ModelForm):
    class Meta:
        model = ShiftTemplate
        fields = ["name", "location", "start_time", "end_time", "break_minutes", "min_headcount", "max_headcount"]
        widgets = {"start_time": forms.TimeInput(attrs={"type": "time"}), "end_time": forms.TimeInput(attrs={"type": "time"})}

class ShiftAssignmentForm(forms.Form):
    employee = forms.ModelMultipleChoiceField(
        queryset=Employee.objects.all(),
        label=_("Employees"),
        widget=forms.SelectMultiple(attrs={"size": 8}),
        help_text=_("Hold Ctrl (or Command) to select more than one employee."),
    )
    location = forms.ModelChoiceField(queryset=Location.objects.all())
    starts_at = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )
    ends_at = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )
    override_reason = forms.CharField(required=False, widget=forms.Textarea)

    def __init__(self, *args, inherited_shift=False, **kwargs):
        super().__init__(*args, **kwargs)
        if inherited_shift:
            for name in ("location", "starts_at", "ends_at"):
                self.fields[name].widget = forms.HiddenInput()

class AvailabilityForm(forms.ModelForm):
    class Meta:
        model = Availability
        fields = ["employee", "starts_at", "ends_at", "available", "source", "notes"]
        widgets = {"starts_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}), "ends_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"})}

class AbsenceForm(forms.ModelForm):
    class Meta:
        model = Absence
        fields = ["employee", "starts_at", "ends_at", "category", "status", "notes"]
        widgets = {"starts_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}), "ends_at": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"})}

class RosterWishForm(forms.ModelForm):
    weekdays = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple, choices=[("0", _("Monday")), ("1", _("Tuesday")), ("2", _("Wednesday")), ("3", _("Thursday")), ("4", _("Friday")), ("5", _("Saturday")), ("6", _("Sunday"))], label=_("Preferred weekdays"), help_text=_("Choose recurring weekdays the employee prefers to work. Other weekdays in this period are avoided where possible."))
    class Meta:
        model = RosterWish
        fields = ["employee", "starts_on", "ends_on", "preferred_location", "date_preference", "desired_day_off", "note"]
        widgets = {"starts_on": ISODateInput(), "ends_on": ISODateInput()}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        hints = {
            "employee": _("The employee whose preference is being recorded."),
            "starts_on": _("First day this wish applies. For one exact date, use the same date in both fields."),
            "ends_on": _("Last day this wish applies. Set equal to the first date for an exact-date wish."),
            "preferred_location": _("Optional. Gives this location extra weight when the draft is generated."),
            "date_preference": _("Wanted favors a date; unwanted means avoid it if possible. Neither blocks assignment."),
            "desired_day_off": _("A stronger wish to keep this date range free. Use an approved absence when work must not be scheduled."),
            "note": _("Optional manager context; it does not change the automatic score."),
        }
        for name, hint in hints.items():
            self.fields[name].help_text = hint
            self.fields[name].widget.attrs["title"] = hint
        self.fields["weekdays"].widget.attrs["title"] = self.fields["weekdays"].help_text
        if self.instance.pk: self.fields["weekdays"].initial = [str(day) for day in self.instance.preferred_weekdays]
    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.preferred_weekdays = [int(day) for day in self.cleaned_data["weekdays"]]
        if commit: instance.save()
        return instance

class GenerationRequestForm(forms.Form):
    starts_on = forms.DateField(label=_("Planning starts on"), input_formats=["%Y-%m-%d"], widget=ISODateInput(), help_text=_("Assignments before this date stay fixed; the solver changes this date through month-end."))
    def __init__(self, roster, *args, **kwargs):
        self.roster = roster
        super().__init__(*args, **kwargs)
        self.fields["starts_on"].initial = roster.month
    def clean_starts_on(self):
        starts_on = self.cleaned_data["starts_on"]
        month_end = (self.roster.month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if not self.roster.month <= starts_on <= month_end: raise forms.ValidationError(_("Choose a date within this roster month."))
        return starts_on

class MonthlyShiftTargetForm(forms.Form):
    def __init__(self, roster, *args, **kwargs):
        super().__init__(*args, **kwargs)
        targets = {item.employee_id: item.target_shifts for item in roster.employee_targets.all()}
        for employee in Employee.objects.filter(active=True).order_by("name"):
            self.fields[f"employee_{employee.pk}"] = forms.IntegerField(
                label=employee.name,
                min_value=0,
                required=False,
                initial=targets.get(employee.pk),
            )

class LegacyRosterImportForm(forms.Form):
    template = forms.ModelChoiceField(queryset=ShiftTemplate.objects.select_related("location").all(), label=_("Shift template"))
    matrix = forms.CharField(
        label=_("Pasted roster"),
        widget=forms.Textarea(attrs={"rows": 14, "spellcheck": "false"}),
        help_text=_("Paste a range copied from Excel. The first row must contain day numbers; the first column must contain employee names. Any non-empty day cell creates an assignment."),
    )
