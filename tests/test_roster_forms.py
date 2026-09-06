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
def test_roster_creation_uses_and_accepts_native_month_input():
    form = RosterCreateForm()
    assert 'type="month"' in form["month"].as_widget()

    submitted = RosterCreateForm({"month": "2026-02"})
    assert submitted.is_valid()
    assert submitted.cleaned_data["month"] == date(2026, 2, 1)
