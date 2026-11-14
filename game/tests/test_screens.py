from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from game import bonuses
from game.models import BonusUse, Competition, Jumper, Player, Result, Weekend


@pytest.fixture
def world(django_user_model):
    users = [
        django_user_model.objects.create_user(f"u{i}", password="haslo-12345") for i in range(1, 4)
    ]
    players = [
        Player.objects.create(user=u, name=f"Gracz{i}", order=i) for i, u in enumerate(users, 1)
    ]
    men = [
        Jumper.objects.create(name=f"MEN{i}", country="POL", gender="M", external_id=f"m{i}")
        for i in range(1, 13)
    ]
    women = [
        Jumper.objects.create(name=f"WOM{i}", country="SLO", gender="K", external_id=f"k{i}")
        for i in range(1, 4)
    ]
    weekend = Weekend.objects.create(name="Lillehammer", start_date=timezone.now().date())
    competition = Competition.objects.create(
        weekend=weekend,
        name="HS140 M",
        gender="M",
        start_at=timezone.now() + timedelta(days=1),
        external_id="1",
    )
    return {
        "users": users,
        "players": players,
        "men": men,
        "women": women,
        "weekend": weekend,
        "competition": competition,
    }


def login(client, user):
    client.login(username=user.username, password="haslo-12345")


# --- Ekrany tylko do odczytu --------------------------------------------------------------------


@pytest.mark.django_db
def test_screens_require_login(client, world):
    for name, args in [
        ("home", []),
        ("team", []),
        ("weekends", []),
        ("weekend_detail", [world["weekend"].pk]),
        ("draft", []),
    ]:
        response = client.get(reverse(name, args=args))
        assert response.status_code == 302, name
        assert reverse("login") in response["Location"]


@pytest.mark.django_db
def test_home_shows_ranking_with_points(client, world):
    p1, p2, _ = world["players"]
    world["men"][0].owner = p1
    world["men"][0].save()
    world["men"][1].owner = p2
    world["men"][1].save()
    Result.objects.create(competition=world["competition"], jumper=world["men"][0], rank=1)
    Result.objects.create(competition=world["competition"], jumper=world["men"][1], rank=2)
    login(client, world["users"][0])
    html = client.get(reverse("home")).content.decode()
    assert "Gracz1" in html
    assert ">60<" in html  # 50 pkt + 10 premii za wygrany weekend
    assert ">40<" in html


@pytest.mark.django_db
def test_my_team_page_lists_jumpers_and_bonuses(client, world):
    p1 = world["players"][0]
    world["men"][0].owner = p1
    world["men"][0].save()
    world["women"][0].owner = p1
    world["women"][0].save()
    BonusUse.objects.create(player=p1, code=bonuses.NORWAY, weekend=world["weekend"])
    login(client, world["users"][0])
    html = client.get(reverse("team")).content.decode()
    assert "Moja drużyna" in html
    assert "MEN1" in html
    assert "WOM1" in html
    assert "Norweg" in html
    assert "1/1" in html  # użyty Norweg


@pytest.mark.django_db
def test_other_players_team_is_visible(client, world):
    p2 = world["players"][1]
    world["men"][3].owner = p2
    world["men"][3].save()
    login(client, world["users"][0])
    html = client.get(reverse("team_of", args=[p2.pk])).content.decode()
    assert "Drużyna: Gracz2" in html
    assert "MEN4" in html


@pytest.mark.django_db
def test_user_without_player_gets_friendly_message(client, django_user_model):
    user = django_user_model.objects.create_user("obcy", password="haslo-12345")
    login(client, user)
    assert "nie jest jeszcze graczem" in client.get(reverse("team")).content.decode()
    assert client.get(reverse("home")).status_code == 200


@pytest.mark.django_db
def test_weekends_split_into_upcoming_and_started(client, world):
    past = Weekend.objects.create(name="Stary", start_date=timezone.now().date())
    Competition.objects.create(
        weekend=past,
        name="Dawny",
        gender="M",
        start_at=timezone.now() - timedelta(days=3),
        external_id="2",
    )
    login(client, world["users"][0])
    html = client.get(reverse("weekends")).content.decode()
    upcoming_part, past_part = html.split("Rozpoczęte i zakończone")
    assert "Lillehammer" in upcoming_part
    assert "Stary" in past_part
    assert "Stary" not in upcoming_part


@pytest.mark.django_db
def test_weekend_detail_shows_score_breakdown(client, world):
    p1 = world["players"][0]
    world["men"][0].owner = p1
    world["men"][0].save()
    Result.objects.create(competition=world["competition"], jumper=world["men"][0], rank=1)
    login(client, world["users"][0])
    html = client.get(reverse("weekend_detail", args=[world["weekend"].pk])).content.decode()
    assert "MEN1" in html
    assert "Premia za najlepszy wynik weekendu" in html
    assert "HS140 M" in html


@pytest.mark.django_db
def test_weekend_detail_404(client, world):
    login(client, world["users"][0])
    assert client.get(reverse("weekend_detail", args=[9999])).status_code == 404


# --- Draft ----------------------------------------------------------------------------------


def draft_data(world, assignment):
    """assignment: {player_index: ([men indices], woman index or None)}"""
    data = {}
    for p_index, player in enumerate(world["players"]):
        men, woman = assignment.get(p_index, ([], None))
        for slot in range(5):
            data[f"{player.pk}-m{slot + 1}"] = world["men"][men[slot]].pk if slot < len(men) else ""
        data[f"{player.pk}-k1"] = world["women"][woman].pk if woman is not None else ""
    return data


@pytest.mark.django_db
def test_draft_forbidden_for_regular_player(client, world):
    login(client, world["users"][0])
    assert client.get(reverse("draft")).status_code == 403
    assert client.post(reverse("draft"), {}).status_code == 403


@pytest.mark.django_db
def test_draft_page_renders_for_staff(client, world, django_user_model):
    staff = django_user_model.objects.create_user("szef", password="haslo-12345", is_staff=True)
    login(client, staff)
    response = client.get(reverse("draft"))
    assert response.status_code == 200
    assert "Gracz1" in response.content.decode()


@pytest.mark.django_db
def test_draft_assigns_rosters(client, world, django_user_model):
    staff = django_user_model.objects.create_user("szef", password="haslo-12345", is_staff=True)
    login(client, staff)
    data = draft_data(world, {0: ([0, 1, 2, 3, 4], 0), 1: ([5, 6], 1)})
    response = client.post(reverse("draft"), data)
    assert response.status_code == 302
    p1, p2, p3 = world["players"]
    assert p1.jumpers.filter(gender="M").count() == 5
    assert p1.jumpers.filter(gender="K").count() == 1
    assert p2.jumpers.count() == 3
    assert p3.jumpers.count() == 0


@pytest.mark.django_db
def test_draft_rejects_same_jumper_for_two_players(client, world, django_user_model):
    staff = django_user_model.objects.create_user("szef", password="haslo-12345", is_staff=True)
    login(client, staff)
    data = draft_data(world, {0: ([0, 1], None), 1: ([1, 2], None)})
    response = client.post(reverse("draft"), data)
    assert response.status_code == 200
    assert "MEN2 jest wybrany więcej niż raz" in response.content.decode()
    assert Jumper.objects.filter(owner__isnull=False).count() == 0


@pytest.mark.django_db
def test_draft_rejects_same_jumper_twice_in_one_team(client, world, django_user_model):
    staff = django_user_model.objects.create_user("szef", password="haslo-12345", is_staff=True)
    login(client, staff)
    data = draft_data(world, {0: ([0, 0], None)})
    response = client.post(reverse("draft"), data)
    assert response.status_code == 200
    assert Jumper.objects.filter(owner__isnull=False).count() == 0


@pytest.mark.django_db
def test_draft_replaces_previous_rosters(client, world, django_user_model):
    p1 = world["players"][0]
    for jumper in world["men"][:3]:
        jumper.owner = p1
        jumper.save()
    staff = django_user_model.objects.create_user("szef", password="haslo-12345", is_staff=True)
    login(client, staff)
    client.post(reverse("draft"), draft_data(world, {0: ([5], None)}))
    assert list(p1.jumpers.values_list("name", flat=True)) == ["MEN6"]


@pytest.mark.django_db
def test_draft_form_cannot_pick_inactive_jumper(client, world, django_user_model):
    world["men"][0].active = False
    world["men"][0].save()
    staff = django_user_model.objects.create_user("szef", password="haslo-12345", is_staff=True)
    login(client, staff)
    response = client.post(reverse("draft"), draft_data(world, {0: ([0], None)}))
    assert response.status_code == 200
    assert Jumper.objects.filter(owner__isnull=False).count() == 0
