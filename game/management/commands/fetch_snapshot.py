from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand

from game.importers import snapshot


class Command(BaseCommand):
    help = (
        "Pobiera dane ze skijumping.pl do plików JSON (data/skijumping). "
        "Nie używa bazy - uruchamia to GitHub Actions, a serwer wczytuje pliki przez load_snapshot."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(settings.BASE_DIR / "data" / "skijumping"))
        parser.add_argument("--season", default="2025-2026", help="Sezon klasyfikacji skoczków.")
        parser.add_argument("--refresh-jumpers", action="store_true")

    def handle(self, *args, dir, season, refresh_jumpers, **options):
        today = datetime.now(ZoneInfo("Europe/Warsaw")).date()
        summary = snapshot.fetch_snapshot(
            Path(dir),
            today=today,
            season=season,
            refresh_jumpers=refresh_jumpers,
            log=self.stdout.write,
        )
        self.stdout.write(self.style.SUCCESS(f"Gotowe: {summary}"))
