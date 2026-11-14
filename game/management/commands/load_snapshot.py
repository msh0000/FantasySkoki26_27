from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from game.importers.sync import load_snapshot


class Command(BaseCommand):
    help = "Wczytuje do bazy dane z plików data/skijumping (kalendarz, skoczkowie, wyniki)."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(settings.BASE_DIR / "data" / "skijumping"))

    def handle(self, *args, dir, **options):
        summary = load_snapshot(Path(dir))
        self.stdout.write(self.style.SUCCESS(f"Wczytano: {summary}"))
