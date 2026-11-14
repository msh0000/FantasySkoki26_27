import pytest

from game import rules
from game.rules import FEMALE, MALE, TCS, WC


@pytest.mark.parametrize(
    ("rank", "points"),
    [(1, 50), (2, 40), (3, 35), (4, 29), (5, 27), (6, 25), (7, 24), (15, 16), (30, 1), (31, 0)],
)
def test_men_world_cup_points(rank, points):
    assert rules.points_for_rank(MALE, WC, rank) == points


@pytest.mark.parametrize(("rank", "points"), [(1, 20), (2, 18), (5, 12), (10, 2), (11, 0)])
def test_women_points(rank, points):
    assert rules.points_for_rank(FEMALE, WC, rank) == points
    assert rules.points_for_rank(FEMALE, TCS, rank) == points  # TCS kobiet jak zwykły konkurs


@pytest.mark.parametrize(("rank", "points"), [(1, 50), (2, 45), (5, 30), (10, 5), (11, 0)])
def test_men_tcs_points(rank, points):
    assert rules.points_for_rank(MALE, TCS, rank) == points


def test_missing_rank_gives_zero():
    assert rules.points_for_rank(MALE, WC, None) == 0


def test_reversed_points():
    assert rules.reversed_points(MALE, 1) == 1
    assert rules.reversed_points(MALE, 30) == 30
    assert rules.reversed_points(MALE, 31) == 0
    assert rules.reversed_points(FEMALE, 11) == 0


def test_transfer_fee():
    assert [rules.transfer_fee(n) for n in range(4)] == [0, 0, -5, -10]


def test_queue_order_worst_first_with_tiebreak():
    standings = {1: 100, 2: 50, 3: 50, 4: 10}
    # Remis 2 vs 3: gracz o mniejszym `order` jest wyżej w rankingu, więc idzie później.
    assert rules.queue_order(standings, {1: 1, 2: 2, 3: 3, 4: 4}) == [4, 3, 2, 1]


def test_queue_blocks_until_previous_resolved():
    queue = [4, 3, 2, 1]
    assert rules.can_act_in_queue(queue, set(), 4)
    assert not rules.can_act_in_queue(queue, set(), 3)
    assert rules.can_act_in_queue(queue, {4}, 3)
    assert not rules.can_act_in_queue(queue, {4}, 2)
    assert not rules.can_act_in_queue(queue, {4}, 4)  # już ruszył, czeka na resztę


def test_queue_opens_for_everyone_after_last_player():
    queue = [4, 3, 2, 1]
    assert rules.can_act_in_queue(queue, {1, 2, 3, 4}, 4)
    assert rules.can_act_in_queue(queue, {1, 2, 3, 4}, 1)


def test_players_to_confirm_skip():
    assert rules.players_to_confirm_skip([4, 3, 2, 1], {4}, 2) == [3]
    assert rules.players_to_confirm_skip([4, 3, 2, 1], set(), 4) == []
