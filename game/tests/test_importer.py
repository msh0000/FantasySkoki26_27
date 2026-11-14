from datetime import date, timedelta
from pathlib import Path

import pytest
from django.utils import timezone

from game.importers import skijumping_pl as sp
from game.importers import sync
from game.models import Competition, Jumper, Result, Weekend

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- Parsery --------------------------------------------------------------------------------


def test_parse_women_individual_results():
    parsed = sp.parse_results(fixture("result_women_individual.html"))
    assert "Pań" in parsed.title
    assert len(parsed.rows) == 40
    first = parsed.rows[0]
    assert (first.external_id, first.name, first.country, first.rank) == (
        "2680",
        "MARUYAMA Nozomi",
        "JPN",
        1,
    )
    assert first.points == 285.5
    last = parsed.rows[-1]
    assert last.rank is None
    assert last.status == "DSQ"


def test_parse_men_individual_keeps_tied_ranks():
    parsed = sp.parse_results(fixture("result_men_individual.html"))
    ranks = [r.rank for r in parsed.rows]
    assert len(ranks) == 50
    assert ranks.count(28) == 2
    assert 29 not in ranks
    assert parsed.rows[0].country == "AUT"


def test_parse_duet_with_disqualifications():
    parsed = sp.parse_results(fixture("result_men_duet.html"))
    assert [r.rank for r in parsed.rows].count(None) == 4
    assert parsed.rows[0].external_id == "3495"


def test_gender_ranks_for_regular_competition_use_site_ranks():
    parsed = sp.parse_results(fixture("result_men_team.html"))
    ranks = sp.gender_ranks(parsed.rows, {}, "M")
    assert ranks[parsed.rows[0].external_id] == 1
    assert sorted(set(ranks.values()))[:3] == [1, 2, 3]
    assert list(ranks.values()).count(6) == 2  # remis na 6. miejscu


def test_gender_ranks_for_mixed_competition_are_computed_per_gender():
    parsed = sp.parse_results(fixture("result_mixed_team.html"))
    assert len(parsed.rows) == 60
    by_slug = {r.slug: r for r in parsed.rows}
    women = {by_slug[s].external_id for s in ("nika-prevc", "nozomi-maruyama", "abigail-strate")}
    genders = {r.external_id: ("K" if r.external_id in women else "M") for r in parsed.rows}
    ranks = sp.gender_ranks(parsed.rows, genders, "X")

    # Kobiety (257.7, 254.6, 252.3 pkt) mają własną klasyfikację 1-3.
    assert sorted(ranks[w] for w in women) == [1, 2, 3]
    # Mężczyzna z 10. miejsca wspólnej tabeli jest 9. wśród mężczyzn (Nika była przed nim).
    tenth = next(r for r in parsed.rows if r.rank == 10)
    assert ranks[tenth.external_id] == 9


def test_parse_jumpers_from_standings():
    jumpers = sp.parse_jumpers(fixture("standings_ps.html"))
    assert len(jumpers) > 50
    assert (jumpers[0].external_id, jumpers[0].country) == ("2523", "SLO")
    assert len({j.external_id for j in jumpers}) == len(jumpers)


def test_country_code_falls_back_to_prefix():
    assert sp.country_code("Polska") == "POL"
    assert sp.country_code("Wyspy Zielonego Przylądka") == "WYS"


# --- Kalendarz ------------------------------------------------------------------------------


def test_parse_calendar_and_kinds():
    men = sp.parse_calendar(fixture("calendar_ps.html"))
    first = men[0]
    assert (first.external_id, first.city, first.day, first.kind, first.series_code) == (
        "5752",
        "Lillehammer",
        date(2026, 11, 20),
        "mixed",
        "ps",
    )
    assert {e.kind for e in men} >= {"individual", "team", "mixed"}


def test_mixed_competitions_are_merged_between_men_and_women_lists():
    men = sp.parse_calendar(fixture("calendar_ps.html"))
    women = sp.parse_calendar(fixture("calendar_lps.html"))
    merged = sp.merge_calendars(men, women)
    assert len({e.external_id for e in merged}) == len(merged)
    assert len(merged) < len(men) + len(women)
    assert sum(e.kind == "mixed" for e in merged) == 4


def test_weekend_grouping_and_tcs_detection():
    men = sp.parse_calendar(fixture("calendar_ps.html"))
    women = sp.parse_calendar(fixture("calendar_lps.html"))
    groups = sp.group_weekends(sp.merge_calendars(men, women))
    lillehammer = groups[0]
    assert {e.city for e in lillehammer} == {"Lillehammer"}
    assert len(lillehammer) >= 4  # 3 konkursy M + konkursy K, mieszany liczony raz
    tcs = [e for g in groups for e in g if sp.is_tcs(e)]
    assert {e.city for e in tcs} == {
        "Oberstdorf",
        "Garmisch-Partenkirchen",
        "Innsbruck",
        "Bischofshofen",
    }


# --- Zapis do bazy --------------------------------------------------------------------------


def _competition(gender: str, external_id: str) -> Competition:
    weekend = Weekend.objects.create(name="Test", start_date=timezone.now().date())
    return Competition.objects.create(
        weekend=weekend,
        name="Konkurs",
        gender=gender,
        start_at=timezone.now() + timedelta(days=1),
        external_id=external_id,
    )


@pytest.mark.django_db
def test_import_calendar_creates_weekends_and_is_idempotent():
    men = sp.parse_calendar(fixture("calendar_ps.html"))
    women = sp.parse_calendar(fixture("calendar_lps.html"))
    first = sync.import_calendar(men, women)
    assert first["created"] == len(sp.merge_calendars(men, women))

    by_id = {c.external_id: c for c in Competition.objects.all()}
    assert by_id["5752"].gender == "X"  # mieszany
    assert by_id["5753"].gender == "M"
    assert by_id["5794"].gender == "K"
    assert by_id["5764"].series == "TCS"
    assert by_id["5752"].weekend.name == "Lillehammer"

    by_id["5753"].start_at += timedelta(hours=3)
    by_id["5753"].save()
    expected_start = by_id["5753"].start_at

    second = sync.import_calendar(men, women)
    assert second["created"] == 0
    assert Competition.objects.count() == first["created"]
    assert Competition.objects.get(external_id="5753").start_at == expected_start


@pytest.mark.django_db
def test_import_results_creates_jumpers_and_is_idempotent():
    comp = _competition("M", "5543")
    report = sync.import_results(comp, fixture("result_men_individual.html"))
    assert report.saved == 50
    assert len(report.created_jumpers) == 50
    assert Jumper.objects.filter(gender="M").count() == 50

    sync.import_results(comp, fixture("result_men_individual.html"))
    assert Result.objects.filter(competition=comp).count() == 50
    winner = Result.objects.get(competition=comp, rank=1)
    assert winner.jumper.external_id == "3495"


@pytest.mark.django_db
def test_import_results_without_rank_for_disqualified():
    comp = _competition("K", "5586")
    report = sync.import_results(comp, fixture("result_women_individual.html"))
    assert report.saved == 40
    assert len(report.no_rank) == 1
    assert Result.objects.get(competition=comp, jumper__external_id__isnull=False, rank=None)


@pytest.mark.django_db
def test_mixed_results_need_known_gender_then_rank_per_gender():
    comp = _competition("X", "5542")
    first = sync.import_results(comp, fixture("result_mixed_team.html"))
    assert first.saved == 0
    assert len(first.unknown_gender) == 60

    parsed = sp.parse_results(fixture("result_mixed_team.html"))
    women_slugs = {"nika-prevc", "nozomi-maruyama", "abigail-strate"}
    for row in parsed.rows:
        Jumper.objects.create(
            name=row.name,
            country=row.country,
            gender="K" if row.slug in women_slugs else "M",
            external_id=row.external_id,
        )
    second = sync.import_results(comp, fixture("result_mixed_team.html"))
    assert second.saved == 60
    women_ranks = sorted(
        Result.objects.filter(competition=comp, jumper__gender="K").values_list("rank", flat=True)
    )
    assert women_ranks == [1, 2, 3]


def test_world_championship_calendar_has_gender_hints():
    entries = sp.parse_calendar(fixture("calendar_ms.html"))
    hints = {e.external_id: (e.kind, e.gender_hint) for e in entries}
    assert hints["5782"] == ("team", "K")  # drużynowy pań
    assert hints["5784"] == ("mixed", "")
    assert hints["5785"] == ("individual", "M")
    assert hints["5786"] == ("team", "")  # drużynowy mężczyzn (bez dopisku)


@pytest.mark.django_db
def test_world_championship_competitions_get_correct_gender_and_series():
    men = sp.parse_calendar(fixture("calendar_ps.html"))
    women = sp.parse_calendar(fixture("calendar_lps.html"))
    ms = sp.parse_calendar(fixture("calendar_ms.html"))
    sync.import_calendar(men, women, ms)
    by_id = {c.external_id: c for c in Competition.objects.filter(series="WCH")}
    assert by_id["5782"].gender == "K"
    assert by_id["5783"].gender == "K"
    assert by_id["5784"].gender == "X"
    assert by_id["5785"].gender == "M"
    assert by_id["5786"].gender == "M"


def test_parse_profile_gender():
    assert sp.parse_profile_gender("<p>Zobacz wyniki skoczkini w konkursach</p>") == "K"
    assert sp.parse_profile_gender("<p>Zobacz wyniki skoczka w konkursach</p>") == "M"
    assert sp.parse_profile_gender("<p>nic</p>") == ""


@pytest.mark.django_db
def test_mixed_results_resolve_unknown_gender_from_profiles():
    comp = _competition("X", "5542")
    women_slugs = {"nika-prevc", "nozomi-maruyama", "abigail-strate"}

    def fake_profiles(path: str) -> str:
        slug = path.strip("/").split("/")[-1]
        return "Zobacz wyniki skoczkini" if slug in women_slugs else "Zobacz wyniki skoczka"

    report = sync.import_results(
        comp, fixture("result_mixed_team.html"), profile_fetcher=fake_profiles
    )
    assert report.saved == 60
    assert report.unknown_gender == []
    assert Jumper.objects.filter(gender="K").count() == 3
    women_ranks = sorted(
        Result.objects.filter(competition=comp, jumper__gender="K").values_list("rank", flat=True)
    )
    assert women_ranks == [1, 2, 3]


# --- Migawki (GitHub Actions -> pliki -> serwer) ---------------------------------------------


def fake_site(today_results: set[str]):
    """Udaje skijumping.pl na podstawie zapisanych stron."""
    pages = {
        "/zawody/ps": fixture("calendar_ps.html"),
        "/zawody/lps": fixture("calendar_lps.html"),
        "/zawody/ms": fixture("calendar_ms.html"),
    }
    calls: list[str] = []

    def fetch(path: str) -> str:
        calls.append(path)
        if path in pages:
            return pages[path]
        if path.startswith("/wyniki/klasyfikacja/ps/"):
            return fixture("standings_ps.html")
        if path.startswith("/wyniki/klasyfikacja/lps/"):
            return "<html></html>"
        if path.startswith("/zawodnicy/"):
            return "Zobacz wyniki skoczka"
        external_id = path.rsplit("/", 1)[-1]
        if external_id in today_results:
            return fixture("result_men_individual.html")
        return "<html><body>brak</body></html>"

    return fetch, calls


def test_fetch_snapshot_writes_files_and_is_idempotent(tmp_path):
    from game.importers import snapshot

    fetch, calls = fake_site({"5753"})  # konkurs M z 21.11.2026
    today = date(2026, 11, 21)
    first = snapshot.fetch_snapshot(tmp_path, today=today, fetch=fetch)
    assert first["results_fetched"] == 1
    assert (tmp_path / "calendar.json").exists()
    assert (tmp_path / "jumpers.json").exists()
    assert (tmp_path / "results" / "5753.json").exists()
    # Konkursy z przyszłości nie są pobierane.
    assert not any(c.endswith("/5770") for c in calls)

    second = snapshot.fetch_snapshot(tmp_path, today=today, fetch=fetch)
    assert second["changed_files"] == 0  # te same dane = brak zmian w plikach


def test_fetch_snapshot_does_not_refetch_old_results(tmp_path):
    from game.importers import snapshot

    fetch, calls = fake_site({"5753"})
    snapshot.fetch_snapshot(tmp_path, today=date(2026, 11, 21), fetch=fetch)
    calls.clear()
    # Tydzień później wyniki konkursu 5753 są już "stare" - nie pobieramy ich ponownie.
    snapshot.fetch_snapshot(tmp_path, today=date(2026, 11, 29), fetch=fetch)
    assert "/wyniki/zawody/5753" not in calls


def test_fetch_snapshot_resolves_genders_for_mixed_competition(tmp_path):
    from game.importers import snapshot

    pages = {
        "/zawody/ps": fixture("calendar_ps.html"),
        "/zawody/lps": fixture("calendar_lps.html"),
        "/zawody/ms": fixture("calendar_ms.html"),
    }

    def fetch(path: str) -> str:
        if path in pages:
            return pages[path]
        if path.startswith("/wyniki/klasyfikacja/"):
            return "<html></html>"
        if path.startswith("/zawodnicy/"):
            return "Zobacz wyniki skoczkini" if "nika-prevc" in path else "Zobacz wyniki skoczka"
        if path == "/wyniki/zawody/5752":  # mieszany, 20.11.2026
            return fixture("result_mixed_team.html")
        return "<html></html>"

    snapshot.fetch_snapshot(tmp_path, today=date(2026, 11, 20), fetch=fetch)
    genders = snapshot.read_genders(tmp_path)
    assert len(genders) == 60
    assert genders["3016"] == "K"  # Nika Prevc
    assert genders["3258"] == "M"


@pytest.mark.django_db
def test_load_snapshot_fills_database(tmp_path):
    from game.importers import snapshot

    fetch, _ = fake_site({"5753"})
    snapshot.fetch_snapshot(tmp_path, today=date(2026, 11, 21), fetch=fetch)

    summary = sync.load_snapshot(tmp_path)
    assert summary["competitions_created"] == 74
    competition = Competition.objects.get(external_id="5753")
    assert Result.objects.filter(competition=competition).count() == 50
    assert Jumper.objects.filter(gender="M").count() >= 50

    again = sync.load_snapshot(tmp_path)  # drugie wczytanie niczego nie dubluje
    assert again["competitions_created"] == 0
    assert Result.objects.filter(competition=competition).count() == 50
