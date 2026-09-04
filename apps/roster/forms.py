from django import forms
from datetime import timedelta
from .models import Absence, Availability, RosterVersion, RosterWish, ShiftAssignment, ShiftTemplate

class MonthInput(forms.DateInput):
    input_type = "month"

class RosterCreateForm(forms.ModelForm):
    class Meta:
        model = RosterVersion
        fields = ["month"]
        widgets = {"month": MonthInput()}
        input_formats = ["%Y-%m", "%Y-%m-%d"]
    def clean_month(self):
        month = self.cleaned_data["month"]
        return month.replace(day=1)

class ShiftTemplateForm(forms.ModelForm):
    class Meta:
        model = ShiftTemplate
        fields = ["name", "location", "start_time", "end_time", "break_minutes", "min_headcount", "max_headcount"]
        widgets = {"start_time": forms.TimeInput(attrs={"type": "time"}), "end_time": forms.TimeInput(attrs={"type": "time"})}

class ShiftAssignmentForm(forms.ModelForm):
    class Meta:
        model = ShiftAssignment
        fields = ["employee", "location", "starts_at", "ends_at", "override_reason"]
        widgets = {"starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}

class AvailabilityForm(forms.ModelForm):
    class Meta:
        model = Availability
        fields = ["employee", "starts_at", "ends_at", "available", "source", "notes"]
        widgets = {"starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}

class AbsenceForm(forms.ModelForm):
    class Meta:
        model = Absence
        fields = ["employee", "starts_at", "ends_at", "category", "status", "notes"]
        widgets = {"starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}), "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}

class RosterWishForm(forms.ModelForm):
    weekdays = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple, choices=[("0", "Monday"), ("1", "Tuesday"), ("2", "Wednesday"), ("3", "Thursday"), ("4", "Friday"), ("5", "Saturday"), ("6", "Sunday")], label="Preferred weekdays", help_text="Choose recurring weekdays the employee prefers to work. Other weekdays in this period are avoided where possible.")
    class Meta:
        model = RosterWish
        fields = ["employee", "starts_on", "ends_on", "preferred_location", "date_preference", "desired_day_off", "note"]
        widgets = {"starts_on": forms.DateInput(attrs={"type": "date"}), "ends_on": forms.DateInput(attrs={"type": "date"})}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        hints = {
            "employee": "The employee whose preference is being recorded.",
            "starts_on": "First day this wish applies. For one exact date, use the same date in both fields.",
            "ends_on": "Last day this wish applies. Set equal to the first date for an exact-date wish.",
            "preferred_location": "Optional. Gives this location extra weight when the draft is generated.",
            "date_preference": "Wanted favors a date; unwanted means avoid it if possible. Neither blocks assignment.",
            "desired_day_off": "A stronger wish to keep this date range free. Use an approved absence when work must not be scheduled.",
            "note": "Optional manager context; it does not change the automatic score.",
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
    starts_on = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), help_text="Assignments before this date stay fixed; the solver changes this date through month-end.")
    def __init__(self, roster, *args, **kwargs):
        self.roster = roster
        super().__init__(*args, **kwargs)
        self.fields["starts_on"].initial = roster.month
    def clean_starts_on(self):
        starts_on = self.cleaned_data["starts_on"]
        month_end = (self.roster.month.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if not self.roster.month <= starts_on <= month_end: raise forms.ValidationError("Choose a date within this roster month.")
        return starts_on
