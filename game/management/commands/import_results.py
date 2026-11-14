from django.core.management.base import BaseCommand, CommandError

from game.importers import skijumping_pl as sp
from game.importers.sync import import_results
from game.models import Competition


class Command(BaseCommand):
    help = "Pobiera wyniki konkursu ze skijumping.pl. Podaj numer konkursu z serwisu (external_id)."

    def add_arguments(self, parser):
        parser.add_argument("external_id")

    def handle(self, *args, external_id, **options):
        try:
            competition = Competition.objects.get(external_id=external_id)
        except Competition.DoesNotExist as exc:
            raise CommandError(f"Brak konkursu z external_id={external_id}") from exc
        report = import_results(
            competition, sp.fetch(sp.results_path(external_id)), profile_fetcher=sp.fetch
        )
        self.stdout.write(self.style.SUCCESS(f"{competition}: zapisano {report.saved} wyników."))
        for label, items in (
            ("Nowi zawodnicy", report.created_jumpers),
            ("Nieznana płeć (ustaw w adminie i uruchom ponownie)", report.unknown_gender),
            ("Bez miejsca", report.no_rank),
        ):
            if items:
                self.stdout.write(f"{label}: {', '.join(items)}")
