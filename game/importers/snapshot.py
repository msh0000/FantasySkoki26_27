"""Pliki-migawki z danymi ze skijumping.pl (kalendarz, skoczkowie, wyniki) zapisywane w repo.

Po co: darmowy PythonAnywhere nie ma dostępu do skijumping.pl, ale ma dostęp do GitHuba.
Dane pobiera więc GitHub Actions (`fetch_snapshot`) i commituje je jako pliki JSON, a serwer
po `git pull` wczytuje je do bazy (`load_snapshot`). Ten moduł nie używa Django ani bazy.

Układ katalogu:
    calendar.json    - kalendarze z list PŚ M, PŚ K i MŚ
    jumpers.json     - skoczkowie startowi (klasyfikacje poprzedniego sezonu)
    genders.json     - płeć zawodników z konkursów mieszanych (id -> "M"/"K")
    results/<id>.json - wyniki jednego konkursu
Pliki są deterministyczne (bez znaczników czasu), żeby bez zmian danych nie było commitów.
"""

import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from . import skijumping_pl as sp

RECENT_DAYS = 2  # wyniki z ostatnich dni pobieramy ponownie (mogły być niepełne lub poprawione)


def write_json(path: Path, data) -> bool:
    """Zapisuje JSON tylko gdy treść się zmieniła. Zwraca True, jeśli plik został zmieniony."""
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _entry_to_json(entry: sp.CalendarEntry) -> dict:
    return {**asdict(entry), "day": entry.day.isoformat()}


def _entry_from_json(data: dict) -> sp.CalendarEntry:
    return sp.CalendarEntry(**{**data, "day": date.fromisoformat(data["day"])})


# --- Odczyt ---------------------------------------------------------------------------------


def read_calendar(directory: Path) -> dict[str, list[sp.CalendarEntry]]:
    raw = _read_json(directory / "calendar.json", {})
    return {key: [_entry_from_json(e) for e in raw.get(key, [])] for key in ("men", "women", "ms")}


def read_jumpers(directory: Path) -> dict[str, list[sp.JumperRow]]:
    raw = _read_json(directory / "jumpers.json", {})
    return {gender: [sp.JumperRow(**j) for j in raw.get(gender, [])] for gender in ("M", "K")}


def read_genders(directory: Path) -> dict[str, str]:
    return _read_json(directory / "genders.json", {})


def read_results(directory: Path) -> dict[str, list[sp.ResultRow]]:
    """id konkursu -> wiersze wyników."""
    results = {}
    for path in sorted((directory / "results").glob("*.json")):
        raw = _read_json(path, {})
        results[path.stem] = [sp.ResultRow(**row) for row in raw.get("rows", [])]
    return results


# --- Pobieranie -----------------------------------------------------------------------------


def fetch_snapshot(
    directory: Path,
    *,
    today: date,
    fetch: Callable[[str], str] = sp.fetch,
    season: str = "2025-2026",
    refresh_jumpers: bool = False,
    log: Callable[[str], None] = lambda message: None,
) -> dict[str, int]:
    """Pobiera dane ze skijumping.pl do plików w `directory`. Nie dotyka bazy danych."""
    changed = 0

    calendar = {
        "men": sp.parse_calendar(fetch("/zawody/ps")),
        "women": sp.parse_calendar(fetch("/zawody/lps")),
        "ms": sp.parse_calendar(fetch("/zawody/ms")),
    }
    changed += write_json(
        directory / "calendar.json",
        {key: [_entry_to_json(e) for e in entries] for key, entries in calendar.items()},
    )

    jumpers_path = directory / "jumpers.json"
    if refresh_jumpers or not jumpers_path.exists():
        men = sp.parse_jumpers(fetch(f"/wyniki/klasyfikacja/ps/{season}"))
        women = sp.parse_jumpers(fetch(f"/wyniki/klasyfikacja/lps/{season}"))
        changed += write_json(
            jumpers_path,
            {"M": [asdict(j) for j in men], "K": [asdict(j) for j in women]},
        )

    genders = read_genders(directory)
    for gender, rows in read_jumpers(directory).items():
        for row in rows:
            genders.setdefault(row.external_id, gender)

    fetched = 0
    for entry in sp.merge_calendars(*calendar.values()):
        if entry.day > today:
            continue
        path = directory / "results" / f"{entry.external_id}.json"
        if path.exists() and entry.day < today - timedelta(days=RECENT_DAYS):
            continue
        parsed = sp.parse_results(fetch(sp.results_path(entry.external_id)))
        if not parsed.rows:
            log(f"Konkurs {entry.external_id} ({entry.city} {entry.day}): brak wyników.")
            continue
        if entry.kind == "mixed":
            # W konkursie mieszanym trzeba znać płeć każdego zawodnika - czytamy ją z profilu.
            for row in parsed.rows:
                if row.external_id not in genders:
                    page = fetch(sp.profile_path(row.external_id, row.slug))
                    if gender := sp.parse_profile_gender(page):
                        genders[row.external_id] = gender
        changed += write_json(
            path,
            {
                "external_id": entry.external_id,
                "title": parsed.title,
                "rows": [asdict(row) for row in parsed.rows],
            },
        )
        fetched += 1
        log(f"Konkurs {entry.external_id} ({entry.city} {entry.day}): {len(parsed.rows)} wyników.")

    changed += write_json(directory / "genders.json", genders)
    return {"changed_files": int(changed), "results_fetched": fetched}
