from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from game import bonuses, services
from game.models import BonusUse, Competition, Jumper, Player, Result, Weekend


@pytest.fixture
def setup(django_user_model):
    players = [
        Player.objects.create(
            user=django_user_model.objects.create_user(f"u{i}", password="x"), name=f"P{i}", order=i
        )
        for i in range(1, 4)
    ]
    a = Jumper.objects.create(name="A", country="POL", gender="M", owner=players[0])
    b = Jumper.objects.create(name="B", country="NOR", gender="M", owner=players[1])
    free = Jumper.objects.create(name="Wolny", country="AUT", gender="M")
    woman = Jumper.objects.create(name="Kobieta", country="SLO", gender="K")
    weekend = Weekend.objects.create(name="Lillehammer", start_date=timezone.now().date())
    comp = Competition.objects.create(
        weekend=weekend, name="HS140", gender="M", start_at=timezone.now() + timedelta(days=1)
    )
    return {
        "players": players,
        "a": a,
        "b": b,
        "free": free,
        "woman": woman,
        "weekend": weekend,
        "comp": comp,
    }


@pytest.mark.django_db
def test_weekend_scores_from_results(setup):
    comp = setup["comp"]
    Result.objects.create(competition=comp, jumper=setup["a"], rank=1)
    Result.objects.create(competition=comp, jumper=setup["b"], rank=2)
    scores = services.weekend_scores(setup["weekend"])
    p1, p2, p3 = setup["players"]
    assert scores[p1.id].total == 50 + 10
    assert scores[p2.id].total == 40
    assert scores[p3.id].total == 0


@pytest.mark.django_db
def test_roster_snapshot_keeps_old_team_after_transfer(setup):
    p1 = setup["players"][0]
    comp = setup["comp"]
    services.snapshot_rosters(comp)
    services.make_transfer(setup["weekend"], p1, setup["a"], setup["free"], enforce_queue=False)
    Result.objects.create(competition=comp, jumper=setup["a"], rank=1)
    assert services.weekend_scores(setup["weekend"])[p1.id].total == 50 + 10


@pytest.mark.django_db
def test_transfer_rules(setup):
    p1, p2, _ = setup["players"]
    weekend = setup["weekend"]
    with pytest.raises(services.TransferError):  # cudzy zawodnik
        services.make_transfer(weekend, p1, setup["b"], setup["free"], enforce_queue=False)
    with pytest.raises(services.TransferError):  # zajęty zawodnik
        services.make_transfer(weekend, p1, setup["a"], setup["b"], enforce_queue=False)
    with pytest.raises(services.TransferError):  # inna płeć
        services.make_transfer(weekend, p1, setup["a"], setup["woman"], enforce_queue=False)
    services.make_transfer(weekend, p1, setup["a"], setup["free"], enforce_queue=False)
    setup["free"].refresh_from_db()
    assert setup["free"].owner == p1


@pytest.mark.django_db
def test_transfer_locked_after_weekend_start(setup):
    weekend = setup["weekend"]
    with pytest.raises(services.TransferError):
        services.make_transfer(
            weekend,
            setup["players"][0],
            setup["a"],
            setup["free"],
            enforce_queue=False,
            now=timezone.now() + timedelta(days=2),
        )


@pytest.mark.django_db
def test_queue_flow_worst_player_first_then_free_for_all(setup):
    p1, p2, p3 = setup["players"]
    weekend = setup["weekend"]
    slots = services.build_queue(weekend)
    # Brak punktów: remis, wyżej w bazie (P1) idzie ostatni.
    assert [s.player_id for s in slots] == [p3.id, p2.id, p1.id]
    assert services.can_transfer(weekend, p3)
    assert not services.can_transfer(weekend, p1)
    assert services.players_to_confirm_skip(weekend, p1) == [p3, p2]

    services.finish_turn(weekend, p3)
    services.finish_turn(weekend, p2)
    assert services.can_transfer(weekend, p1)
    services.finish_turn(weekend, p1)
    assert services.can_transfer(weekend, p3)  # po przejściu kolejki każdy może


@pytest.mark.django_db
def test_bonus_use_validation_in_model(setup):
    p1, p2, _ = setup["players"]
    BonusUse.objects.create(player=p2, code=bonuses.NORWAY, weekend=setup["weekend"])
    duel = BonusUse(player=p1, code=bonuses.DUEL, weekend=setup["weekend"], target_player=p2)
    with pytest.raises(ValidationError):
        duel.full_clean()
