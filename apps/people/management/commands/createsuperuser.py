"""Project-specific superuser creation behavior."""

from django.contrib.auth.management.commands import createsuperuser
from django.contrib.auth.management.commands.createsuperuser import Command as DjangoCommand


class Command(DjangoCommand):
    """Require an explicit username instead of suggesting the OS account name."""

    def handle(self, *args, **options):
        original_get_default_username = createsuperuser.get_default_username
        createsuperuser.get_default_username = lambda database=None: ""
        try:
            return super().handle(*args, **options)
        finally:
            createsuperuser.get_default_username = original_get_default_username
