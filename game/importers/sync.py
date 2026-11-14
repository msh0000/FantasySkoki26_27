"""Zapis danych pobranych z skijumping.pl do bazy (kalendarz, skoczkowie, wyniki)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from game import rules
from game.models import Competition, Jumper, Result, Weekend

from . import skijumping_pl as sp
from . import snapshot
from .jumper_list import ListRow
from .names import names_match

DEFAULT_START = time(12, 0)  # strona podaje tylko daty - godziny poprawiamy w adminie

KIND_LABELS = {
    "individual": "indywidualny",
    "team": "drużynowy",
    "duet": "duety",
    "mixed": "mieszany",
}
GENDER_TAGS = {rules.MALE: "M", rules.FEMALE: "K", rules.MIXED: "mix"}


def _competition_gender(entry: sp.CalendarEntry, men_ids: set[str], women_ids: set[str]) -> str:
    if entry.kind == "mixed":
        return rules.MIXED
    if entry.gender_hint:
        return entry.gender_hint
    if entry.external_id in women_ids and entry.external_id not in men_ids:
        return rules.FEMALE
    return rules.MALE


@transaction.atomic
def import_calendar(
    men: list[sp.CalendarEntry],
    women: list[sp.CalendarEntry],
    extra: list[sp.CalendarEntry] | None = None,
) -> dict[str, int]:
    """Tworzy/aktualizuje weekendy i konkursy. Bezpieczne do wielokrotnego uruchamiania."""
    men_ids = {e.external_id for e in men}
    women_ids = {e.external_id for e in women}
    merged = sp.merge_calendars(men, women, extra or [])
    created = updated = 0
    tz = timezone.get_current_timezone()
    for group in sp.group_weekends(merged):
        first = group[0]
        weekend, _ = Weekend.objects.get_or_create(
            name=first.city, start_date=first.day, defaults={"place": first.city}
        )
        for entry in group:
            gender = _competition_gender(entry, men_ids, women_ids)
            if entry.series_code == "ms":
                series = rules.WCH
            else:
                series = rules.TCS if sp.is_tcs(entry) else rules.WC
            defaults = {
                "weekend": weekend,
                "name": (
                    f"{entry.city} {entry.day:%d.%m} {KIND_LABELS[entry.kind]} "
                    f"({GENDER_TAGS[gender]})"
                ),
                "gender": gender,
                "series": series,
            }
            start_at = timezone.make_aware(datetime.combine(entry.day, DEFAULT_START), tz)
            competition, is_new = Competition.objects.get_or_create(
                external_id=entry.external_id, defaults={**defaults, "start_at": start_at}
            )
            if is_new:
                created += 1
            else:
                # start_at zostaje, bo admin mógł wpisać prawdziwą godzinę
                for field_name, value in defaults.items():
                    setattr(competition, field_name, value)
                competition.save()
                updated += 1
    return {"created": created, "updated": updated}


@transaction.atomic
def import_jumpers(rows: list[sp.JumperRow], gender: str) -> dict[str, int]:
    created = existing = 0
    for row in rows:
        # Pulę do wyboru wyznacza lista z pliku (import_jumper_list), więc nowi są nieaktywni.
        _, is_new = Jumper.objects.get_or_create(
            external_id=row.external_id,
            defaults={
                "name": row.name,
                "country": row.country,
                "gender": gender,
                "active": False,
            },
        )
        created += is_new
        existing += not is_new
    return {"created": created, "existing": existing}


@transaction.atomic
def import_jumper_list(rows: list[ListRow], *, deactivate_others: bool = True) -> dict[str, int]:
    """Wczytuje listę zawodników w grze: dopasowuje do istniejących (numer lub nazwisko),
    uzupełnia dane, ustawia ich jako aktywnych, a pozostałych (spoza listy) jako nieaktywnych.
    """
    existing = list(Jumper.objects.all())
    by_external = {j.external_id: j for j in existing if j.external_id}
    created = updated = 0
    listed_ids: set[int] = set()

    for row in rows:
        jumper = by_external.get(row.external_id) if row.external_id else None
        if jumper is None:
            candidates = [j for j in existing if j.id not in listed_ids and j.gender == row.gender]
            jumper = next((j for j in candidates if names_match(j.name, row.name)), None)
        if jumper is None:
            jumper = Jumper.objects.create(
                name=row.name,
                country=row.country,
                gender=row.gender,
                external_id=row.external_id,
            )
            existing.append(jumper)
            created += 1
        else:
            jumper.gender = row.gender or jumper.gender
            jumper.country = row.country or jumper.country
            if row.external_id and not jumper.external_id:
                jumper.external_id = row.external_id
            updated += 1
        jumper.active = True
        jumper.save()
        listed_ids.add(jumper.id)

    deactivated = 0
    if deactivate_others:
        deactivated = (
            Jumper.objects.exclude(id__in=listed_ids).filter(active=True).update(active=False)
        )
    return {"created": created, "updated": updated, "deactivated": deactivated}


@dataclass
class ResultsReport:
    saved: int = 0
    created_jumpers: list[str] = field(default_factory=list)
    unknown_gender: list[str] = field(default_factory=list)
    no_rank: list[str] = field(default_factory=list)


@transaction.atomic
def save_results(
    competition: Competition,
    rows: list[sp.ResultRow],
    genders: dict[str, str] | None = None,
) -> ResultsReport:
    """Zapisuje wyniki konkursu (miejsca w klasyfikacji płci).

    `genders` (id zawodnika -> "M"/"K") służy do ustalenia płci nowych zawodników w konkursach
    mieszanych; w pozostałych płeć wynika z typu konkursu.
    """
    genders = genders or {}
    report = ResultsReport()
    known = {j.external_id: j for j in Jumper.objects.exclude(external_id="")}

    without_id = [j for j in Jumper.objects.filter(external_id="")]

    for row in rows:
        if row.external_id in known:
            continue
        gender = (
            genders.get(row.external_id, "")
            if competition.gender == rules.MIXED
            else competition.gender
        )
        if not gender:
            report.unknown_gender.append(f"{row.name} ({row.external_id})")
            continue
        # Zawodnik z listy gry bez numeru ze skijumping.pl: dopasowujemy po nazwisku.
        match = next(
            (j for j in without_id if j.gender == gender and names_match(j.name, row.name)), None
        )
        if match is not None:
            without_id.remove(match)
            match.external_id = row.external_id
            match.country = match.country or row.country
            match.save()
            known[row.external_id] = match
            continue
        known[row.external_id] = Jumper.objects.create(
            name=row.name,
            country=row.country,
            gender=gender,
            external_id=row.external_id,
            active=False,  # spoza listy gry - do włączenia w adminie
        )
        report.created_jumpers.append(row.name)

    gender_by_id = {ext: j.gender for ext, j in known.items()}
    ranks = sp.gender_ranks(rows, gender_by_id, competition.gender)
    for row in rows:
        jumper = known.get(row.external_id)
        if jumper is None:
            continue
        rank = ranks.get(row.external_id)
        if rank is None:
            report.no_rank.append(f"{row.name}: {row.status or 'brak'}")
        Result.objects.update_or_create(
            competition=competition, jumper=jumper, defaults={"rank": rank}
        )
        report.saved += 1
    return report


def import_results(
    competition: Competition,
    page_html: str,
    profile_fetcher: Callable[[str], str] | None = None,
) -> ResultsReport:
    """Zapisuje wyniki ze strony skijumping.pl (pobranej bezpośrednio, np. lokalnie)."""
    rows = sp.parse_results(page_html).rows
    genders: dict[str, str] = {}
    if competition.gender == rules.MIXED and profile_fetcher:
        known_ids = set(
            Jumper.objects.exclude(external_id="").values_list("external_id", flat=True)
        )
        for row in rows:
            if row.external_id not in known_ids:
                page = profile_fetcher(sp.profile_path(row.external_id, row.slug))
                if gender := sp.parse_profile_gender(page):
                    genders[row.external_id] = gender
    return save_results(competition, rows, genders)


def load_snapshot(directory: Path) -> dict[str, int]:
    """Wczytuje do bazy dane z plików-migawek (kalendarz, skoczkowie, wyniki)."""
    summary = {"competitions_created": 0, "results_saved": 0, "results_skipped": 0}

    calendar = snapshot.read_calendar(directory)
    if any(calendar.values()):
        summary["competitions_created"] = import_calendar(
            calendar["men"], calendar["women"], calendar["ms"]
        )["created"]

    for gender, rows in snapshot.read_jumpers(directory).items():
        import_jumpers(rows, gender)

    genders = snapshot.read_genders(directory)
    for external_id, rows in snapshot.read_results(directory).items():
        competition = Competition.objects.filter(external_id=external_id).first()
        if competition is None:
            summary["results_skipped"] += 1
            continue
        report = save_results(competition, rows, genders)
        summary["results_saved"] += report.saved
    return summary
