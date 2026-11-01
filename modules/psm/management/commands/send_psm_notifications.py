from django.core.management.base import BaseCommand

from modules.psm.services.workflow import deliver_communications


class Command(BaseCommand):
    help = "Deliver pending PSM notification messages from the communication outbox."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        count = deliver_communications(limit=max(1, options["limit"]))
        self.stdout.write(self.style.SUCCESS(f"Delivered {count} PSM notification(s)."))
