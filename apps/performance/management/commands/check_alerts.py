from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.performance.models import AlertRule, ManagerAlert, PerformanceReport
from apps.roster.models import RosterVersion, ShiftAssignment

class Command(BaseCommand):
    help = "Evaluate configured manager-only alert rules."
    def handle(self, *args, **options):
        now = timezone.now(); created = 0
        for assignment in ShiftAssignment.objects.filter(roster_version__status=RosterVersion.PUBLISHED, starts_at__lte=now, ends_at__gte=now).select_related("employee"):
            latest = PerformanceReport.objects.filter(assignment=assignment, status=PerformanceReport.ACCEPTED).first()
            for rule in AlertRule.objects.filter(enabled=True):
                issue = None
                if rule.rule_type == AlertRule.MISSING and (not latest or (now - latest.reported_at).total_seconds() / 60 > rule.grace_minutes): issue = "No report received within the configured interval."
                if rule.rule_type == AlertRule.NO_INCREASE and latest and PerformanceReport.objects.filter(assignment=assignment, status=PerformanceReport.ACCEPTED, employee_total=latest.employee_total).count() > 1: issue = "The cumulative result has not increased."
                if issue:
                    alert, was_created = ManagerAlert.objects.get_or_create(rule=rule, assignment=assignment, employee=assignment.employee, status=ManagerAlert.OPEN, defaults={"severity": rule.severity, "explanation": issue, "report": latest})
                    created += int(was_created)
        self.stdout.write(self.style.SUCCESS(f"Alert evaluation complete; {created} new alerts."))
