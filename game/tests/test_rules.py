from game.rules import next_transfer_player


def test_first_player_goes_first():
    assert next_transfer_player([1, 2, 3], set(), set()) == 1


def test_next_after_done_or_skipped():
    assert next_transfer_player([1, 2, 3], {1}, set()) == 2
    assert next_transfer_player([1, 2, 3], {1}, {2}) == 3


def test_everyone_finished():
    assert next_transfer_player([1, 2], {1}, {2}) is None
