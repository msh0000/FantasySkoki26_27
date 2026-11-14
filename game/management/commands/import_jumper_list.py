from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from game.importers.jumper_list import read_jumper_list
from game.importers.sync import import_jumper_list


class Command(BaseCommand):
    help = "Wczytuje listę zawodników w grze (data/jumpers_list.tsv) i ustawia pulę do wyboru."

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(settings.BASE_DIR / "data" / "jumpers_list.tsv"))
        parser.add_argument(
            "--keep-others",
            action="store_true",
            help="Nie wyłączaj zawodników spoza listy.",
        )

    def handle(self, *args, file, keep_others, **options):
        rows = read_jumper_list(Path(file))
        report = import_jumper_list(rows, deactivate_others=not keep_others)
        self.stdout.write(self.style.SUCCESS(f"Lista ({len(rows)} osób): {report}"))
