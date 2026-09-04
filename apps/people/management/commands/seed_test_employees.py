import random

from django.core.management.base import BaseCommand
from apps.people.models import Employee, Location


class Command(BaseCommand):
    help = "Create clearly marked test employees for manual roster testing. Does not modify existing employees."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=12, help="Number of test employees to create (default: 12).")

    def handle(self, *args, **options):
        count = options["count"]
        if not 1 <= count <= 100:
            self.stderr.write("Count must be between 1 and 100.")
            return
        locations = list(Location.objects.filter(active=True))
        if not locations:
            self.stderr.write(self.style.ERROR("Create at least one active location first, so the test employees can be eligible for it."))
            return
        first_names = ["Anna", "Bohdan", "Daria", "Ihor", "Kateryna", "Maksym", "Natalia", "Oleksii", "Sofia", "Taras", "Viktoriia", "Yurii", "Alina", "Denys", "Iryna"]
        created = 0
        for number in range(1, count + 1):
            name = f"[TEST] {random.choice(first_names)} {number:02d}"
            employee, was_created = Employee.objects.get_or_create(name=name, defaults={"wish_priority": random.randint(1, 5), "role": "Test employee", "notes": "Created by seed_test_employees; archive or remove after testing."})
            if was_created:
                employee.allowed_locations.set(locations)
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Created {created} test employees; {count - created} already existed."))
