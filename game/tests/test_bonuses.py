from game import bonuses as b
from game.bonuses import Bonus, validate_bonus_use


def bonus(code, player=1, weekend=1, competition=None, **kw):
    return Bonus(code=code, player_id=player, weekend_id=weekend, competition_id=competition, **kw)


def test_valid_competition_bonus():
    assert validate_bonus_use(bonus(b.DOUBLE_CAPTAIN, competition=10, target_jumper_id=5), []) == []


def test_competition_bonus_needs_competition():
    assert validate_bonus_use(bonus(b.DOUBLE_CAPTAIN, target_jumper_id=5), [])


def test_weekend_bonus_cannot_have_competition():
    assert validate_bonus_use(bonus(b.NORWAY, competition=10), [])


def test_each_bonus_once_per_season_but_typer_three_times():
    used = bonus(b.DOUBLE_CAPTAIN, weekend=1, competition=10, target_jumper_id=5)
    again = bonus(b.DOUBLE_CAPTAIN, weekend=2, competition=20, target_jumper_id=6)
    assert validate_bonus_use(again, [used])

    picks = (1, 2, 3, 4, 5)
    typers = [bonus(b.TYPER, weekend=i, competition=i * 10, picks=picks) for i in (1, 2)]
    third = bonus(b.TYPER, weekend=3, competition=30, picks=picks)
    assert validate_bonus_use(third, typers) == []
    assert validate_bonus_use(
        bonus(b.TYPER, weekend=4, competition=40, picks=picks), [*typers, third]
    )


def test_only_one_bonus_per_competition_per_player():
    first = bonus(b.DOUBLE_CAPTAIN, competition=10, target_jumper_id=5)
    second = bonus(b.BLACKLIST, competition=10, target_jumper_id=6)
    assert validate_bonus_use(second, [first])
    # inny gracz albo inny konkurs - w porządku
    assert (
        validate_bonus_use(
            bonus(b.BLACKLIST, player=2, competition=10, target_jumper_id=6), [first]
        )
        == []
    )
    assert validate_bonus_use(bonus(b.BLACKLIST, competition=11, target_jumper_id=6), [first]) == []


def test_jumper_can_be_affected_only_once_per_competition():
    first = bonus(b.DOUBLE_CAPTAIN, player=1, competition=10, target_jumper_id=5)
    assert validate_bonus_use(
        bonus(b.BLACKLIST, player=2, competition=10, target_jumper_id=5), [first]
    )


def test_norway_blocks_targeting_bonuses():
    norway = bonus(b.NORWAY, player=2)
    assert validate_bonus_use(bonus(b.DUEL, player=1, target_player_id=2), [norway])
    assert validate_bonus_use(
        bonus(
            b.STEAL,
            player=1,
            competition=10,
            target_player_id=2,
            target_jumper_id=7,
            give_jumper_id=8,
        ),
        [norway],
    )
    assert validate_bonus_use(bonus(b.DUEL, player=1, target_player_id=3), [norway]) == []


def test_norway_unavailable_if_already_targeted():
    duel = bonus(b.DUEL, player=1, target_player_id=2)
    assert validate_bonus_use(bonus(b.NORWAY, player=2), [duel])
    assert validate_bonus_use(bonus(b.NORWAY, player=2, weekend=2), [duel]) == []


def test_duel_and_steal_cannot_target_self_but_blacklist_can():
    assert validate_bonus_use(bonus(b.DUEL, player=1, target_player_id=1), [])
    assert (
        validate_bonus_use(bonus(b.BLACKLIST, player=1, competition=10, target_jumper_id=5), [])
        == []
    )


def test_typer_and_dream_team_pick_counts():
    assert validate_bonus_use(bonus(b.TYPER, competition=10, picks=(1, 2, 3)), [])
    assert validate_bonus_use(bonus(b.DREAM_TEAM, competition=10, picks=(1, 2, 3, 4, 5)), [])
    assert (
        validate_bonus_use(bonus(b.DREAM_TEAM, competition=10, picks=(1, 2, 3, 4, 5, 6)), []) == []
    )
