from decimal import Decimal
from django.core.exceptions import ValidationError
from .models import EmployeeTargetAllocation

def validate_target_allocations(target):
    total = sum(target.allocations.values_list("allocated_target", flat=True))
    if total != target.target_total: raise ValidationError(f"Allocations total {total}; location target is {target.target_total}.")
    return total

def performance_snapshot(report, allocation=None):
    assignment = report.assignment
    if not assignment or not allocation: return {"pace": None, "expected": None, "difference": None}
    elapsed = max((report.reported_at - assignment.starts_at).total_seconds() / 3600, 0)
    shift = max((assignment.ends_at - assignment.starts_at).total_seconds() / 3600, 0.01)
    expected = float(allocation.allocated_target) * min(elapsed / shift, 1)
    return {"pace": round(report.employee_total / max(elapsed, .01), 2), "expected": round(expected, 2), "difference": round(report.employee_total - expected, 2)}
