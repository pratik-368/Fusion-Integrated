from django.core.management.base import BaseCommand

from modules.psm.services.workflow import run_scheduled_reports


class Command(BaseCommand):
    help = "Generate all due scheduled PSM reports and record their audit events."

    def handle(self, *args, **options):
        count = run_scheduled_reports()
        self.stdout.write(self.style.SUCCESS(f"Generated {count} scheduled PSM report(s)."))
