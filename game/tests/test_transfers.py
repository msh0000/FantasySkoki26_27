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
    owned = [
        Jumper.objects.create(
            name=f"WLASNY{i}", country="POL", gender="M", owner=player, external_id=f"o{i}"
        )
        for i, player in enumerate(players, 1)
    ]
    free = [
        Jumper.objects.create(name=f"WOLNY{i}", country="AUT", gender="M", external_id=f"f{i}")
        for i in range(1, 6)
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


def url(name, setup):
    return reverse(name, args=[setup["weekend"].pk])


def transfer(client, setup, player_index, out_jumper, in_jumper, **extra):
    return client.post(
        url("transfer_make", setup),
        {
            "player": setup["players"][player_index].pk,
            "out": out_jumper.pk,
            "in": in_jumper.pk,
            **extra,
        },
        follow=True,
    )


def confirm_skips(client, setup, player_index, **extra):
    return client.post(
        url("transfer_confirm", setup),
        {"player": setup["players"][player_index].pk, **extra},
        follow=True,
    )


def pass_turn(client, setup, player_index, **extra):
    return client.post(
        url("transfer_pass", setup),
        {"player": setup["players"][player_index].pk, **extra},
        follow=True,
    )


def statuses(setup):
    return {slot.player.name: slot.status for slot in setup["weekend"].queue.all()}


def open_window(setup):
    services.build_queue(setup["weekend"])  # remis na 0: kolejka G3, G2, G1


# --- Okno transferowe ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_transfers_page_before_window_opens(client, setup):
    login(client, setup["users"][0])
    html = client.get(reverse("transfers")).content.decode()
    assert "Okno transferowe nie zostało jeszcze otwarte" in html
    assert "Otwórz okno transferowe" not in html  # przycisk tylko dla admina


@pytest.mark.django_db
def test_only_staff_can_open_window(client, setup, django_user_model):
    login(client, setup["users"][0])
    assert client.post(url("transfer_open", setup)).status_code == 403
    staff = django_user_model.objects.create_user("szef", password="haslo-12345", is_staff=True)
    login(client, staff)
    assert client.post(url("transfer_open", setup)).status_code == 302
    assert setup["weekend"].queue.count() == 3


@pytest.mark.django_db
def test_transfer_blocked_until_window_open(client, setup):
    login(client, setup["users"][0])
    response = transfer(client, setup, 0, setup["owned"][0], setup["free"][0])
    assert "nie zostało jeszcze otwarte" in response.content.decode()
    assert Transfer.objects.count() == 0


# --- Tura gracza: nielimitowane transfery, koniec tury oddaje pałeczkę ---------------------------


@pytest.mark.django_db
def test_player_out_of_turn_cannot_transfer(client, setup):
    open_window(setup)
    login(client, setup["users"][0])
    response = transfer(client, setup, 0, setup["owned"][0], setup["free"][0])  # G1 przed kolejką
    assert "jeszcze nie Twoja kolej" in response.content.decode()
    assert Transfer.objects.count() == 0


@pytest.mark.django_db
def test_player_can_make_unlimited_transfers_in_own_turn(client, setup):
    open_window(setup)
    login(client, setup["users"][0])
    g3 = setup["players"][2]

    transfer(client, setup, 2, setup["owned"][2], setup["free"][0])
    assert statuses(setup)["G3"] == QueueSlot.PENDING  # transfer nie kończy tury
    # Drugi i trzeci transfer w tej samej turze: oddaje to, co dopiero wziął.
    transfer(client, setup, 2, setup["free"][0], setup["free"][1])
    response = transfer(client, setup, 2, setup["free"][1], setup["free"][2])
    assert "Kara: -10 pkt" in response.content.decode()
    assert Transfer.objects.filter(player=g3).count() == 3
    assert statuses(setup)["G3"] == QueueSlot.PENDING
    assert not services.can_transfer(setup["weekend"], setup["players"][1])  # G2 nadal czeka


@pytest.mark.django_db
def test_ending_turn_passes_baton_and_records_whether_transfers_were_made(client, setup):
    open_window(setup)
    login(client, setup["users"][0])
    transfer(client, setup, 2, setup["owned"][2], setup["free"][0])
    pass_turn(client, setup, 2)
    assert statuses(setup)["G3"] == QueueSlot.DONE  # coś zrobił
    assert services.can_transfer(setup["weekend"], setup["players"][1])  # teraz G2

    pass_turn(client, setup, 1)  # G2 nic nie zrobił
    assert statuses(setup)["G2"] == QueueSlot.SKIPPED


@pytest.mark.django_db
def test_cannot_end_turn_before_earlier_players_resolved(client, setup):
    open_window(setup)
    login(client, setup["users"][0])
    response = pass_turn(client, setup, 0)  # G1 jest ostatni w kolejce
    assert "Najpierw potwierdź pominięcie" in response.content.decode()
    assert statuses(setup)["G1"] == QueueSlot.PENDING


# --- Jeden przycisk: potwierdzenie pominięcia poprzednich --------------------------------------


@pytest.mark.django_db
def test_confirm_skips_earlier_players_and_makes_it_my_turn(client, setup):
    open_window(setup)
    login(client, setup["users"][0])
    response = confirm_skips(client, setup, 0)  # G1 potwierdza, że G3 i G2 pominęli
    assert "Pominięci: G3, G2" in response.content.decode()
    assert statuses(setup) == {
        "G3": QueueSlot.SKIPPED,
        "G2": QueueSlot.SKIPPED,
        "G1": QueueSlot.PENDING,
    }
    # Teraz jego kolej: dowolnie wiele transferów, potem koniec.
    transfer(client, setup, 0, setup["owned"][0], setup["free"][0])
    transfer(client, setup, 0, setup["free"][0], setup["free"][1])
    pass_turn(client, setup, 0)
    assert statuses(setup)["G1"] == QueueSlot.DONE
    assert Transfer.objects.filter(player=setup["players"][0]).count() == 2


@pytest.mark.django_db
def test_confirmed_skip_keeps_done_status_for_player_who_already_transferred(client, setup):
    open_window(setup)
    login(client, setup["users"][0])
    transfer(client, setup, 2, setup["owned"][2], setup["free"][0])  # G3 zrobił ruch, nie zakończył
    confirm_skips(client, setup, 1)  # G2 potwierdza pominięcie G3
    assert statuses(setup)["G3"] == QueueSlot.DONE


@pytest.mark.django_db
def test_confirm_does_nothing_when_nobody_is_waiting(client, setup):
    open_window(setup)
    login(client, setup["users"][0])
    response = confirm_skips(client, setup, 2)  # G3 jest pierwszy
    assert "to już Twoja kolej" in response.content.decode()
    assert set(statuses(setup).values()) == {QueueSlot.PENDING}


# --- Po przejściu kolejki: kto pierwszy -----------------------------------------------------------


@pytest.mark.django_db
def test_free_for_all_after_queue_finishes_with_fees(client, setup):
    open_window(setup)
    login(client, setup["users"][0])
    for index in (2, 1, 0):
        pass_turn(client, setup, index) if index != 0 else None
    confirm_skips(client, setup, 0)  # G1: wszyscy przed nim pominęli
    pass_turn(client, setup, 0)
    assert set(statuses(setup).values()) == {QueueSlot.SKIPPED}

    # Kolejka skończona: każdy może działać, w tym G2 przed G1.
    transfer(client, setup, 1, setup["owned"][1], setup["free"][0])
    transfer(client, setup, 1, setup["free"][0], setup["free"][1])  # drugi - kara
    assert Transfer.objects.filter(player=setup["players"][1]).count() == 2
    Result.objects.create(competition=setup["competition"], jumper=setup["free"][1], rank=1)
    score = services.weekend_scores(setup["weekend"])[setup["players"][1].pk]
    assert ("Kara za dodatkowe transfery", -5) in score.lines


# --- Blokada weekendu, uprawnienia, walidacja ---------------------------------------------------


@pytest.mark.django_db
def test_locked_weekend_rejects_players_but_staff_can_override(client, setup, django_user_model):
    open_window(setup)
    setup["competition"].start_at = timezone.now() - timedelta(hours=1)
    setup["competition"].save()
    login(client, setup["users"][0])
    response = transfer(client, setup, 2, setup["owned"][2], setup["free"][0])
    assert "Weekend już się rozpoczął" in response.content.decode()
    assert Transfer.objects.count() == 0
    assert "Weekend już się rozpoczął" in confirm_skips(client, setup, 0).content.decode()
    assert "Weekend już się rozpoczął" in pass_turn(client, setup, 2).content.decode()

    staff = django_user_model.objects.create_user("szef", password="haslo-12345", is_staff=True)
    login(client, staff)
    transfer(client, setup, 0, setup["owned"][0], setup["free"][0], override="1")
    assert Transfer.objects.count() == 1


@pytest.mark.django_db
def test_regular_user_cannot_use_override(client, setup):
    open_window(setup)
    login(client, setup["users"][0])
    transfer(client, setup, 0, setup["owned"][0], setup["free"][0], override="1")
    assert Transfer.objects.count() == 0


@pytest.mark.django_db
def test_transfer_requires_both_jumpers_and_rejects_gender_mismatch(client, setup):
    open_window(setup)
    woman = Jumper.objects.create(name="KOBIETA", country="SLO", gender="K", external_id="w1")
    login(client, setup["users"][0])
    response = client.post(
        url("transfer_make", setup),
        {"player": setup["players"][2].pk, "out": setup["owned"][2].pk, "in": ""},
        follow=True,
    )
    assert "Wybierz zawodnika" in response.content.decode()
    response = transfer(client, setup, 2, setup["owned"][2], woman)
    assert "tej samej płci" in response.content.decode()
    assert Transfer.objects.count() == 0


@pytest.mark.django_db
def test_get_requests_to_actions_are_not_allowed(client, setup):
    login(client, setup["users"][0])
    for name in ("transfer_make", "transfer_confirm", "transfer_pass", "transfer_open"):
        assert client.get(url(name, setup)).status_code == 405


# --- Wygląd strony ------------------------------------------------------------------------------


@pytest.mark.django_db
def test_page_shows_confirm_button_for_waiting_and_end_turn_for_current_player(client, setup):
    open_window(setup)
    login(client, setup["users"][0])
    html = client.get(reverse("transfers")).content.decode()
    assert "pominęli transfery" in html  # G1 i G2 czekają, więc mają przycisk potwierdzenia
    assert "Zakończ moją kolejkę" in html  # G3 jest na ruchu
    assert html.count("oddaj pałeczkę dalej") == 1  # przycisk tylko u gracza na ruchu
    assert 'name="confirm"' not in html  # nie ma już drugiego pola potwierdzenia


# --- Zamrażanie składów -------------------------------------------------------------------------


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
