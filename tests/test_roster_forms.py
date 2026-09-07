from datetime import date

import pytest
from django.utils.translation import override

from apps.roster.forms import GenerationRequestForm, RosterCreateForm
from apps.roster.models import RosterVersion


@pytest.mark.django_db
def test_generation_start_date_stays_iso_for_native_date_input_in_russian():
    roster = RosterVersion.objects.create(month=date(2026, 2, 1))

    with override("ru"):
        form = GenerationRequestForm(roster)
        assert 'value="2026-02-01"' in form["starts_on"].as_widget()

        submitted = GenerationRequestForm(roster, {"starts_on": "2026-02-15"})
        assert submitted.is_valid()
        assert submitted.cleaned_data["starts_on"] == date(2026, 2, 15)


@pytest.mark.django_db
def test_roster_creation_uses_month_and_year_selectors():
    form = RosterCreateForm()
    widget = form["month"].as_widget()
    assert 'name="month_0"' in widget
    assert 'name="month_1"' in widget

    submitted = RosterCreateForm({"month_0": "2", "month_1": "2026"})
    assert submitted.is_valid()
    assert submitted.cleaned_data["month"] == date(2026, 2, 1)
