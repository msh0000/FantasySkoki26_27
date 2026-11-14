"""Pobieranie i parsowanie danych z serwisu skijumping.pl (kalendarz, skoczkowie, wyniki).

Same parsery są czystymi funkcjami (tekst HTML -> dane), więc testujemy je na zapisanych
stronach. Pobieranie z sieci jest w `fetch()` i celowo oszczędne (przerwa między zapytaniami).
"""

import html as htmllib
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import date

BASE_URL = "https://www.skijumping.pl"
USER_AGENT = "FantasySkoki-prywatna-gra (hobby, kilka zapytan na weekend)"

# Nazwy krajów z flag na stronie (po polsku) -> kody FIS. Kluczowe jest POL (bonus Patriota).
COUNTRY_CODES = {
    "Polska": "POL",
    "Słowenia": "SLO",
    "Japonia": "JPN",
    "Austria": "AUT",
    "Niemcy": "GER",
    "Norwegia": "NOR",
    "Kanada": "CAN",
    "Finlandia": "FIN",
    "Szwajcaria": "SUI",
    "Włochy": "ITA",
    "Francja": "FRA",
    "Czechy": "CZE",
    "Stany Zjednoczone": "USA",
    "USA": "USA",
    "Rosja": "RUS",
    "Chiny": "CHN",
    "Kazachstan": "KAZ",
    "Ukraina": "UKR",
    "Szwecja": "SWE",
    "Estonia": "EST",
    "Bułgaria": "BUL",
    "Rumunia": "ROU",
    "Turcja": "TUR",
    "Korea Południowa": "KOR",
    "Łotwa": "LAT",
    "Słowacja": "SVK",
    "Hiszpania": "ESP",
    "Białoruś": "BLR",
    "Gruzja": "GEO",
    "Wielka Brytania": "GBR",
    "Holandia": "NED",
    "Węgry": "HUN",
    "Litwa": "LTU",
    "Belgia": "BEL",
    "Australia": "AUS",
    "Dania": "DEN",
    "Chorwacja": "CRO",
    "Serbia": "SRB",
    "Islandia": "ISL",
    "Mongolia": "MGL",
    "Grecja": "GRE",
    "Armenia": "ARM",
    "Azerbejdżan": "AZE",
}

# Turniej Czterech Skoczni: te miejscowości w okolicy przełomu roku (do ręcznej korekty w adminie).
TCS_CITIES = {"oberstdorf", "garmisch-partenkirchen", "innsbruck", "bischofshofen"}


def country_code(polish_name: str) -> str:
    name = polish_name.strip()
    return COUNTRY_CODES.get(name) or name[:3].upper()


def _text(fragment: str) -> str:
    return htmllib.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _rows(table_html: str) -> list[str]:
    return re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.S)


def _cells(row_html: str) -> list[str]:
    return re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)


def _tables(page_html: str) -> list[str]:
    return re.findall(r"<table.*?</table>", page_html, re.S)


def _flag_alt(fragment: str) -> str:
    match = re.search(r'<img[^>]*alt="([^"]*)"', fragment)
    return htmllib.unescape(match.group(1)) if match else ""


# --- Wyniki konkursu ------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultRow:
    external_id: str
    slug: str
    name: str
    country: str  # kod FIS
    rank: int | None  # None = brak miejsca (DSQ, DNS...)
    status: str  # tekst z kolumny "Lp." gdy brak miejsca
    points: float


@dataclass(frozen=True)
class ParsedResults:
    title: str
    rows: list[ResultRow]


def parse_results(page_html: str) -> ParsedResults:
    title_match = re.search(r"<title>(.*?)</title>", page_html, re.S)
    title = _text(title_match.group(1)) if title_match else ""
    rows: list[ResultRow] = []
    for table in _tables(page_html):
        if "<th>Zawodnik</th>" not in table:
            continue
        for row in _rows(table):
            cells = _cells(row)
            link = re.search(r'/zawodnicy/(\d+)/([^/"]+)/?"[^>]*>(.*?)</a>', row, re.S)
            if len(cells) < 4 or not link:
                continue
            place = _text(cells[0])
            try:
                points = float(_text(cells[-1]))
            except ValueError:
                points = 0.0
            rows.append(
                ResultRow(
                    external_id=link.group(1),
                    slug=link.group(2),
                    name=_text(link.group(3)),
                    country=country_code(_flag_alt(cells[2])),
                    rank=int(place) if place.isdigit() else None,
                    status="" if place.isdigit() else place,
                    points=points,
                )
            )
        break  # tylko pierwsza tabela wyników zawodników
    return ParsedResults(title=title, rows=rows)


def gender_ranks(
    rows: list[ResultRow], gender_by_id: dict[str, str], competition_gender: str
) -> dict[str, int]:
    """Miejsca w klasyfikacji swojej płci: id zawodnika -> miejsce.

    W konkursach M i K bierzemy miejsce ze strony. W mieszanych strona podaje jedną wspólną
    tabelę, więc liczymy miejsca osobno dla kobiet i mężczyzn (remis punktowy = to samo miejsce).
    """
    ranked = [r for r in rows if r.rank is not None]
    if competition_gender != "X":
        return {r.external_id: r.rank for r in ranked}
    result: dict[str, int] = {}
    for gender in ("M", "K"):
        group = [r for r in ranked if gender_by_id.get(r.external_id) == gender]
        for r in group:
            result[r.external_id] = 1 + sum(1 for o in group if o.points > r.points)
    return result


# --- Zawodnicy (klasyfikacja sezonowa) ------------------------------------------------------


@dataclass(frozen=True)
class JumperRow:
    external_id: str
    slug: str
    name: str
    country: str


def parse_jumpers(page_html: str) -> list[JumperRow]:
    """Skoczkowie z największej tabeli na stronie klasyfikacji (reszta to boczne ramki)."""
    tables = _tables(page_html)
    if not tables:
        return []
    jumpers: dict[str, JumperRow] = {}
    for row in _rows(max(tables, key=len)):
        link = re.search(r'/zawodnicy/(\d+)/([^/"]+)/?"[^>]*>(.*?)</a>', row, re.S)
        if not link:
            continue
        jumpers.setdefault(
            link.group(1),
            JumperRow(
                external_id=link.group(1),
                slug=link.group(2),
                name=_text(link.group(3)),
                country=country_code(_flag_alt(row)),
            ),
        )
    return list(jumpers.values())


def parse_profile_gender(profile_html: str) -> str:
    """Płeć z profilu zawodnika: "K" ("wyniki skoczkini"), "M" ("wyniki skoczka") albo ""."""
    match = re.search(r"Zobacz wyniki (skoczkini|skoczka)", profile_html)
    if not match:
        return ""
    return "K" if match.group(1) == "skoczkini" else "M"


def profile_path(external_id: str, slug: str) -> str:
    return f"/zawodnicy/{external_id}/{slug}/"


# --- Kalendarz ------------------------------------------------------------------------------


@dataclass(frozen=True)
class CalendarEntry:
    external_id: str
    city: str
    city_slug: str
    day: date
    kind: str  # individual / team / duet / mixed
    series_code: str  # ps, lps, ms (z adresu)
    gender_hint: str = ""  # "K"/"M", gdy opis konkursu mówi to wprost (np. na liście MŚ)


def _info_alts(info_html: str) -> str:
    return " ".join(re.findall(r'alt="([^"]*)"', info_html)).lower()


def _kind(info_html: str) -> str:
    alts = _info_alts(info_html)
    for needle, kind in (
        ("mieszany", "mixed"),
        ("drużynowy", "team"),
        ("duet", "duet"),
    ):
        if needle in alts:
            return kind
    return "individual"


def _gender_hint(info_html: str) -> str:
    alts = _info_alts(info_html)
    if "pań" in alts:
        return "K"
    if "mężczyzn" in alts:
        return "M"
    return ""


def parse_calendar(page_html: str) -> list[CalendarEntry]:
    entries: list[CalendarEntry] = []
    for table in _tables(page_html):
        if "<th>Data</th>" not in table:
            continue
        for row in _rows(table):
            cells = _cells(row)
            link = re.search(r"/zawody/(\d+)/([^/\"]+)/(\w+)/(\d{4}-\d{2}-\d{2})", row)
            if len(cells) < 6 or not link:
                continue
            day, month, year = _text(cells[0]).split("-")
            entries.append(
                CalendarEntry(
                    external_id=link.group(1),
                    city=_text(cells[2]),
                    city_slug=link.group(2),
                    day=date(int(year), int(month), int(day)),
                    kind=_kind(cells[4]),
                    series_code=link.group(3),
                    gender_hint=_gender_hint(cells[4]),
                )
            )
    return entries


def merge_calendars(*calendars: list[CalendarEntry]) -> list[CalendarEntry]:
    """Łączy kalendarze (konkursy mieszane są na listach M i K pod tym samym numerem)."""
    merged: dict[str, CalendarEntry] = {}
    for entry in (e for calendar in calendars for e in calendar):
        merged.setdefault(entry.external_id, entry)
    return sorted(merged.values(), key=lambda e: (e.day, e.external_id))


def group_weekends(entries: list[CalendarEntry]) -> list[list[CalendarEntry]]:
    """Konkursy w tej samej miejscowości, w odstępie do 3 dni, to jeden weekend."""
    groups: list[list[CalendarEntry]] = []
    for entry in sorted(entries, key=lambda e: (e.city_slug, e.day)):
        last = groups[-1][-1] if groups else None
        if last and last.city_slug == entry.city_slug and (entry.day - last.day).days <= 3:
            groups[-1].append(entry)
        else:
            groups.append([entry])
    return sorted(groups, key=lambda g: g[0].day)


def is_tcs(entry: CalendarEntry) -> bool:
    in_window = (entry.day.month == 12 and entry.day.day >= 28) or (
        entry.day.month == 1 and entry.day.day <= 7
    )
    return entry.city_slug in TCS_CITIES and in_window and entry.series_code != "ms"


# --- Sieć -----------------------------------------------------------------------------------


def fetch(path: str, *, pause: float = 1.0) -> str:
    """Pobiera stronę (UTF-8). Robi krótką przerwę, żeby nie męczyć serwisu."""
    time.sleep(pause)
    request = urllib.request.Request(BASE_URL + path, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - stały adres
        return response.read().decode("utf-8", errors="replace")


def results_path(external_id: str) -> str:
    return f"/wyniki/zawody/{external_id}"
