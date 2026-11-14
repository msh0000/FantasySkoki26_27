from django.core.management.base import BaseCommand

from game.importers import skijumping_pl as sp
from game.importers.sync import import_calendar


class Command(BaseCommand):
    help = "Importuje kalendarz sezonu (PŚ M, PŚ K i MŚ) ze skijumping.pl jako weekendy i konkursy."

    def handle(self, *args, **options):
        men = sp.parse_calendar(sp.fetch("/zawody/ps"))
        women = sp.parse_calendar(sp.fetch("/zawody/lps"))
        extra = sp.parse_calendar(sp.fetch("/zawody/ms"))
        report = import_calendar(men, women, extra)
        self.stdout.write(self.style.SUCCESS(f"Kalendarz: {report}"))
        self.stdout.write(
            "Godziny startu są domyślne (12:00) - popraw je w adminie (Konkursy), "
            "a także cykl TCS dla kobiet, jeśli dotyczy."
        )
