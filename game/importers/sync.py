"""Zapis danych pobranych z skijumping.pl do bazy (kalendarz, skoczkowie, wyniki)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, time

from django.db import transaction
from django.utils import timezone

from game import rules
from game.models import Competition, Jumper, Result, Weekend

from . import skijumping_pl as sp

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
        _, is_new = Jumper.objects.get_or_create(
            external_id=row.external_id,
            defaults={"name": row.name, "country": row.country, "gender": gender},
        )
        created += is_new
        existing += not is_new
    return {"created": created, "existing": existing}


@dataclass
class ResultsReport:
    saved: int = 0
    created_jumpers: list[str] = field(default_factory=list)
    unknown_gender: list[str] = field(default_factory=list)
    no_rank: list[str] = field(default_factory=list)


@transaction.atomic
def import_results(
    competition: Competition,
    page_html: str,
    profile_fetcher: Callable[[str], str] | None = None,
) -> ResultsReport:
    """Zapisuje wyniki konkursu (miejsca w klasyfikacji płci) ze strony z wynikami."""
    parsed = sp.parse_results(page_html)
    report = ResultsReport()
    known = {j.external_id: j for j in Jumper.objects.exclude(external_id="")}

    for row in parsed.rows:
        if row.external_id in known:
            continue
        gender = competition.gender
        if gender == rules.MIXED:
            # Konkurs mieszany: płeć nieznanego zawodnika bierzemy z jego profilu.
            gender = ""
            if profile_fetcher:
                gender = sp.parse_profile_gender(
                    profile_fetcher(sp.profile_path(row.external_id, row.slug))
                )
            if not gender:
                report.unknown_gender.append(f"{row.name} ({row.external_id})")
                continue
        known[row.external_id] = Jumper.objects.create(
            name=row.name, country=row.country, gender=gender, external_id=row.external_id
        )
        report.created_jumpers.append(row.name)

    gender_by_id = {ext: j.gender for ext, j in known.items()}
    ranks = sp.gender_ranks(parsed.rows, gender_by_id, competition.gender)
    for row in parsed.rows:
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
