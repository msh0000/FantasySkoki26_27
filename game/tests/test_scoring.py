import pytest

from game import bonuses as b
from game.bonuses import Bonus
from game.rules import FEMALE, MALE, WC
from game.scoring import CompetitionInput, JumperInfo, score_competition, score_weekend

# Zawodnicy 1-5: Polacy/inni mężczyźni, 6: skoczkini.
JUMPERS = {
    1: JumperInfo(MALE, "POL", "Stoch"),
    2: JumperInfo(MALE, "NOR", "Lindvik"),
    3: JumperInfo(MALE, "AUT", "Kraft"),
    4: JumperInfo(MALE, "POL", "Zniszczoł"),
    5: JumperInfo(MALE, "GER", "Wellinger"),
    6: JumperInfo(FEMALE, "SLO", "Prevc"),
}
RANKS = {1: 1, 2: 2, 3: 3, 4: 8, 5: 40, 6: 1}  # punkty: 50, 40, 35, 23, 0, 20


def comp(rosters, *bonus_list, gender=MALE, ranks=None):
    return CompetitionInput(
        label="Konkurs",
        series=WC,
        gender=gender,
        ranks=ranks or RANKS,
        rosters=rosters,
        bonuses=list(bonus_list),
    )


def bonus(code, player=1, **kw):
    return Bonus(code=code, player_id=player, weekend_id=1, competition_id=1, **kw)


def totals(result):
    return {p: s.total for p, s in result.items()}


def test_plain_scoring_sums_roster():
    result = score_competition(comp({1: [1, 4, 6], 2: [2, 3, 5]}), JUMPERS)
    assert totals(result) == {1: 50 + 23 + 20, 2: 40 + 35 + 0}


def test_double_captain():
    result = score_competition(
        comp({1: [1, 4]}, bonus(b.DOUBLE_CAPTAIN, target_jumper_id=1)), JUMPERS
    )
    assert result[1].total == 100 + 23


def test_double_captain_on_other_teams_jumper_affects_that_jumper():
    rosters = {1: [1], 2: [2]}
    result = score_competition(
        comp(rosters, bonus(b.DOUBLE_CAPTAIN, player=1, target_jumper_id=2)), JUMPERS
    )
    assert totals(result) == {1: 50, 2: 80}


def test_blacklist_zeroes_jumper_even_on_own_team():
    result = score_competition(comp({1: [1, 2]}, bonus(b.BLACKLIST, target_jumper_id=1)), JUMPERS)
    assert result[1].total == 40


def test_wind_in_top5_multiplies_and_outside_penalizes():
    ok = score_competition(comp({1: [3]}, bonus(b.WIND, target_jumper_id=3)), JUMPERS)
    assert ok[1].total == 35 * 1.5
    bad = score_competition(comp({1: [4]}, bonus(b.WIND, target_jumper_id=4)), JUMPERS)
    assert bad[1].total == 23 * 1.5 - 10


def test_patriot_adds_extra_pole_or_doubles_own():
    extra = score_competition(comp({1: [2]}, bonus(b.PATRIOT, target_jumper_id=1)), JUMPERS)
    assert extra[1].total == 40 + 50
    own = score_competition(comp({1: [1, 2]}, bonus(b.PATRIOT, target_jumper_id=1)), JUMPERS)
    assert own[1].total == 100 + 40


def test_dream_team_overrides_roster_for_one_competition():
    result = score_competition(
        comp({1: [4], 2: [1, 2]}, bonus(b.DREAM_TEAM, player=1, picks=(1, 2, 3, 5, 4, 6))), JUMPERS
    )
    assert result[1].total == 50 + 40 + 35 + 0 + 23 + 20
    assert result[2].total == 90  # gracz 2 nadal ma swój skład, bez ograniczeń unikalności


def test_steal_swaps_jumpers_between_players():
    steal = bonus(b.STEAL, player=1, target_player_id=2, target_jumper_id=2, give_jumper_id=4)
    result = score_competition(comp({1: [1, 4], 2: [2, 5]}, steal), JUMPERS)
    assert totals(result) == {1: 50 + 40, 2: 23 + 0}


def test_typer_only_for_men_and_exact_place_scores_more():
    typer = bonus(
        b.TYPER, picks=(1, 3, 2, 4, 5)
    )  # trafione: 1 (miejsce 1), 3 (3 vs typ 2), 2 (2 vs typ 3)
    result = score_competition(comp({1: []}, typer), JUMPERS)
    assert result[1].total == 8 + 3 + 3
    women = score_competition(comp({1: []}, typer, gender=FEMALE), JUMPERS)
    assert women[1].total == 0


def test_reversed_points_for_chosen_player():
    result = score_competition(comp({1: [1, 4]}), JUMPERS, reversed_players={1})
    assert result[1].total == 1 + 8


def test_weekend_transfer_fee_adjustment_and_winner_bonus():
    c = comp({1: [1], 2: [2]})
    result = score_weekend(
        competitions=[c],
        jumpers=JUMPERS,
        players=[1, 2],
        transfer_counts={1: 3},  # 2 płatne transfery = -10
        adjustments={2: 5},
    )
    assert totals(result) == {1: 50 - 10, 2: 40 + 5 + 10}  # gracz 2 wygrywa, premia 10


def test_weekend_winner_bonus_goes_to_everyone_on_tie():
    result = score_weekend(
        competitions=[comp({1: [1], 2: [1]}, ranks={1: 1})], jumpers=JUMPERS, players=[1, 2]
    )
    assert totals(result) == {1: 60, 2: 60}


def test_duel_win_and_loss_are_computed_on_pre_duel_totals():
    duel = Bonus(code=b.DUEL, player_id=1, weekend_id=1, target_player_id=2)
    win = score_weekend(
        competitions=[comp({1: [1], 2: [2]})],
        jumpers=JUMPERS,
        players=[1, 2],
        weekend_bonuses=[duel],
    )
    assert win[1].total == 50 + 20 + 10  # wygrał pojedynek i weekend
    assert win[2].total == 40  # przeciwnik bez zmian

    lose = score_weekend(
        competitions=[comp({1: [2], 2: [1]})],
        jumpers=JUMPERS,
        players=[1, 2],
        weekend_bonuses=[duel],
    )
    assert lose[1].total == 40 - 20
    assert lose[2].total == 50 + 10


@pytest.mark.parametrize("players", [[], [1]])
def test_weekend_without_competitions_gives_no_winner_bonus(players):
    result = score_weekend(competitions=[], jumpers=JUMPERS, players=players)
    assert all(s.total == 0 for s in result.values())


def test_no_winner_bonus_when_nobody_scored_anything():
    # Konkurs z wynikami, ale nikt nie ma jeszcze drużyny (np. przed draftem).
    result = score_weekend(competitions=[comp({1: [], 2: []})], jumpers=JUMPERS, players=[1, 2])
    assert totals(result) == {1: 0, 2: 0}


def test_typer_works_in_mixed_competition_for_men():
    from game.rules import MIXED

    typer = bonus(b.TYPER, picks=(1, 2, 3, 4, 5))
    result = score_competition(comp({1: []}, typer, gender=MIXED), JUMPERS)
    assert result[1].total == 8 + 8 + 8  # trafione miejsca 1, 2, 3 (4. poza top 5)
