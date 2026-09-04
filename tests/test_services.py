import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.people.models import Employee, Location
from apps.performance.models import EmployeeTargetAllocation, LocationTarget
from apps.performance.services import validate_target_allocations

@pytest.mark.django_db
def test_target_allocations_must_equal_location_target():
    location = Location.objects.create(name="A")
    employee = Employee.objects.create(name="Ana")
    target = LocationTarget.objects.create(location=location, starts_on=timezone.localdate(), ends_on=timezone.localdate(), target_total=10)
    EmployeeTargetAllocation.objects.create(target=target, employee=employee, allocated_target=9)
    with pytest.raises(ValidationError): validate_target_allocations(target)
