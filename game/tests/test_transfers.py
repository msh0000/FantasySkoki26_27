from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from game import services
from game.models import Competition, Jumper, Player, QueueSlot, Result, Transfer, Weekend


@pytest.fixture
def setup(django_user_model):
    users = [
        django_user_model.objects.create_user(f"u{i}", password="haslo-12345") for i in range(1, 4)
    ]
    players = [Player.objects.create(user=u, name=f"G{i}", order=i) for i, u in enumerate(users, 1)]
    owned = []
    for index, player in enumerate(players, 1):
        owned.append(
            Jumper.objects.create(
                name=f"WLASNY{index}",
                country="POL",
                gender="M",
                owner=player,
                external_id=f"o{index}",
            )
        )
    free = [
        Jumper.objects.create(name=f"WOLNY{i}", country="AUT", gender="M", external_id=f"f{i}")
        for i in range(1, 5)
    ]
    weekend = Weekend.objects.create(name="Lillehammer", start_date=timezone.now().date())
    competition = Competition.objects.create(
        weekend=weekend,
        name="K1",
        gender="M",
        start_at=timezone.now() + timedelta(days=2),
        external_id="1",
    )
    return {
        "users": users,
        "players": players,
        "owned": owned,
        "free": free,
        "weekend": weekend,
        "competition": competition,
    }


def login(client, user):
    client.login(username=user.username, password="haslo-12345")


def post_transfer(client, setup, player_index, out_index, in_index, **extra):
    return client.post(
        reverse("transfer_make", args=[setup["weekend"].pk]),
        {
            "player": setup["players"][player_index].pk,
            "out": setup["owned"][out_index].pk,
            "in": setup["free"][in_index].pk,
            **extra,
        },
        follow=True,
    )


def open_window(setup):
    services.build_queue(setup["weekend"])


@pytest.mark.django_db
def test_transfers_page_before_window_opens(client, setup):
    login(client, setup["users"][0])
    html = client.get(reverse("transfers")).content.decode()
    assert "Okno transferowe nie zostało jeszcze otwarte" in html
    assert "Otwórz okno transferowe" not in html  # przycisk tylko dla admina


@pytest.mark.django_db
def test_only_staff_can_open_window(client, setup, django_user_model):
    url = reverse("transfer_open", args=[setup["weekend"].pk])
    login(client, setup["users"][0])
    assert client.post(url).status_code == 403
    staff = django_user_model.objects.create_user("szef", password="haslo-12345", is_staff=True)
    login(client, staff)
    assert client.post(url).status_code == 302
    assert setup["weekend"].queue.count() == 3


@pytest.mark.django_db
def test_transfer_blocked_until_window_open(client, setup):
    login(client, setup["users"][0])
    response = post_transfer(client, setup, 0, 0, 0)
    assert "nie zostało jeszcze otwarte" in response.content.decode()
    assert Transfer.objects.count() == 0


@pytest.mark.django_db
def test_queue_order_enforced_and_first_transfer_succeeds(client, setup):
    open_window(setup)  # remis na 0: G3 pierwszy, potem G2, potem G1
    login(client, setup["users"][0])
    response = post_transfer(client, setup, 0, 0, 0)  # G1 przed swoją kolejką
    assert "jeszcze nie Twoja kolej" in response.content.decode()
    assert Transfer.objects.count() == 0

    response = post_transfer(client, setup, 2, 2, 0)  # ktoś robi ruch za G3
    assert "WLASNY3 → WOLNY1" in response.content.decode()
    assert Transfer.objects.get().made_by == setup["users"][0]
    setup["free"][0].refresh_from_db()
    assert setup["free"][0].owner == setup["players"][2]
    assert setup["weekend"].queue.get(player=setup["players"][2]).status == QueueSlot.DONE


@pytest.mark.django_db
def test_skip_requires_confirmation_then_unblocks_next(client, setup):
    open_window(setup)
    login(client, setup["users"][0])
    url = reverse("transfer_skip", args=[setup["weekend"].pk])
    g3, g2, _ = setup["players"][2], setup["players"][1], setup["players"][0]

    response = client.post(url, {"player": g2.pk}, follow=True)  # G2 chce pominąć przed G3
    assert "Potwierdź, że pominięcie zgłosili: G3" in response.content.decode()
    assert setup["weekend"].queue.get(player=g2).status == QueueSlot.PENDING

    client.post(url, {"player": g3.pk}, follow=True)  # G3 jest pierwszy - bez potwierdzenia
    assert setup["weekend"].queue.get(player=g3).status == QueueSlot.SKIPPED

    client.post(url, {"player": g2.pk, "confirm": "1"}, follow=True)
    assert setup["weekend"].queue.get(player=g2).status == QueueSlot.SKIPPED
    assert services.can_transfer(setup["weekend"], setup["players"][0])


@pytest.mark.django_db
def test_extra_transfer_costs_points_after_queue_finishes(client, setup):
    open_window(setup)
    login(client, setup["users"][0])
    for index in (2, 1, 0):  # kolejka: G3, G2, G1
        post_transfer(client, setup, index, index, index)
    assert Transfer.objects.count() == 3

    # Drugi transfer G1 (po kolejce): oddaje zawodnika wziętego przed chwilą, kosztuje 5 pkt.
    client.post(
        reverse("transfer_make", args=[setup["weekend"].pk]),
        {
            "player": setup["players"][0].pk,
            "out": setup["free"][0].pk,
            "in": setup["free"][3].pk,
        },
    )
    assert Transfer.objects.filter(player=setup["players"][0]).count() == 2
    Result.objects.create(competition=setup["competition"], jumper=setup["free"][3], rank=1)
    score = services.weekend_scores(setup["weekend"])[setup["players"][0].pk]
    assert ("Kara za dodatkowe transfery", -5) in score.lines


@pytest.mark.django_db
def test_locked_weekend_rejects_players_but_staff_can_override(client, setup, django_user_model):
    open_window(setup)
    setup["competition"].start_at = timezone.now() - timedelta(hours=1)
    setup["competition"].save()
    login(client, setup["users"][0])
    response = post_transfer(client, setup, 2, 2, 0)
    assert "Weekend już się rozpoczął" in response.content.decode()
    assert Transfer.objects.count() == 0

    staff = django_user_model.objects.create_user("szef", password="haslo-12345", is_staff=True)
    login(client, staff)
    post_transfer(client, setup, 0, 0, 0, override="1")  # admin: poza kolejką i blokadą
    assert Transfer.objects.count() == 1


@pytest.mark.django_db
def test_regular_user_cannot_use_override(client, setup):
    open_window(setup)
    login(client, setup["users"][0])
    post_transfer(client, setup, 0, 0, 0, override="1")  # G1 poza kolejką, "override" ignorowany
    assert Transfer.objects.count() == 0


@pytest.mark.django_db
def test_transfer_requires_both_jumpers_and_rejects_gender_mismatch(client, setup):
    open_window(setup)
    woman = Jumper.objects.create(name="KOBIETA", country="SLO", gender="K", external_id="w1")
    login(client, setup["users"][0])
    response = client.post(
        reverse("transfer_make", args=[setup["weekend"].pk]),
        {"player": setup["players"][2].pk, "out": setup["owned"][2].pk, "in": ""},
        follow=True,
    )
    assert "Wybierz zawodnika" in response.content.decode()
    response = client.post(
        reverse("transfer_make", args=[setup["weekend"].pk]),
        {"player": setup["players"][2].pk, "out": setup["owned"][2].pk, "in": woman.pk},
        follow=True,
    )
    assert "tej samej płci" in response.content.decode()
    assert Transfer.objects.count() == 0


@pytest.mark.django_db
def test_get_requests_to_actions_are_not_allowed(client, setup):
    login(client, setup["users"][0])
    for name in ("transfer_make", "transfer_skip", "transfer_open"):
        assert client.get(reverse(name, args=[setup["weekend"].pk])).status_code == 405


@pytest.mark.django_db
def test_started_competition_rosters_are_frozen_before_roster_changes(setup):
    """Transfer po starcie konkursu nie zmienia wstecz punktów tego konkursu."""
    competition = setup["competition"]
    competition.start_at = timezone.now() - timedelta(hours=2)
    competition.save()
    assert competition.roster_locked is False
    Result.objects.create(competition=competition, jumper=setup["owned"][0], rank=1)

    services.make_transfer(
        setup["weekend"],
        setup["players"][0],
        setup["owned"][0],
        setup["free"][0],
        enforce_queue=False,
        enforce_lock=False,
    )
    competition.refresh_from_db()
    assert competition.roster_locked is True
    scores = services.weekend_scores(setup["weekend"])
    assert scores[setup["players"][0].pk].total == 50 + 10  # nadal liczy się stary skład
