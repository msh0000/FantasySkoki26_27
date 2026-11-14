from django.core.management.base import BaseCommand

from game.importers import skijumping_pl as sp
from game.importers.sync import import_jumpers


class Command(BaseCommand):
    help = "Dodaje skoczków z klasyfikacji PŚ wybranego sezonu (lista bazowa, potem uzupełnij)."

    def add_arguments(self, parser):
        parser.add_argument("--season", default="2025-2026")

    def handle(self, *args, season, **options):
        men = sp.parse_jumpers(sp.fetch(f"/wyniki/klasyfikacja/ps/{season}"))
        women = sp.parse_jumpers(sp.fetch(f"/wyniki/klasyfikacja/lps/{season}"))
        self.stdout.write(f"Mężczyźni: {import_jumpers(men, 'M')}")
        self.stdout.write(f"Kobiety: {import_jumpers(women, 'K')}")
