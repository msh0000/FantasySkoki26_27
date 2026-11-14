from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from game import bonuses as b
from game import services
from game.models import BonusUse, Competition, Jumper, Player, Result, Weekend


@pytest.fixture
def world(django_user_model):
    users = [
        django_user_model.objects.create_user(f"u{i}", password="haslo-12345") for i in range(1, 4)
    ]
    players = [Player.objects.create(user=u, name=f"G{i}", order=i) for i, u in enumerate(users, 1)]
    men = [
        Jumper.objects.create(name=f"M{i}", country="POL" if i == 1 else "AUT", gender="M")
        for i in range(1, 13)
    ]
    women = [Jumper.objects.create(name=f"K{i}", country="SLO", gender="K") for i in range(1, 4)]
    # G1: M1, M2; G2: M3, M4, K1; G3: M5
    for jumper, owner in [
        (men[0], players[0]),
        (men[1], players[0]),
        (men[2], players[1]),
        (men[3], players[1]),
        (women[0], players[1]),
        (men[4], players[2]),
    ]:
        jumper.owner = owner
        jumper.save()
    weekend = Weekend.objects.create(name="Lillehammer", start_date=timezone.now().date())
    start = timezone.now() + timedelta(days=2)
    men_comp = Competition.objects.create(
        weekend=weekend, name="M1", gender="M", start_at=start, external_id="1"
    )
    women_comp = Competition.objects.create(
        weekend=weekend, name="K1", gender="K", start_at=start + timedelta(hours=3), external_id="2"
    )
    return {
        "users": users,
        "players": players,
        "men": men,
        "women": women,
        "weekend": weekend,
        "men_comp": men_comp,
        "women_comp": women_comp,
    }


def use(world, player_index, code, **kwargs):
    kwargs.setdefault("weekend", world["weekend"])
    return services.use_bonus(player=world["players"][player_index], code=code, **kwargs)


def errors_of(world, player_index, code, **kwargs) -> list[str]:
    with pytest.raises(services.BonusError) as caught:
        use(world, player_index, code, **kwargs)
    return caught.value.errors


# --- Zasady poszczególnych bonusów ----------------------------------------------------------------


@pytest.mark.django_db
def test_double_captain_on_any_jumper_in_competition_gender(world):
    created = use(
        world, 0, b.DOUBLE_CAPTAIN, competition=world["men_comp"], target_jumper=world["men"][2]
    )
    assert created.target_jumper == world["men"][2]  # zawodnik z cudzej drużyny - wolno
    assert (
        "zła płeć"
        in errors_of(
            world,
            1,
            b.DOUBLE_CAPTAIN,
            competition=world["men_comp"],
            target_jumper=world["women"][0],
        )[0]
    )


@pytest.mark.django_db
def test_blacklist_can_target_own_jumper(world):
    use(world, 0, b.BLACKLIST, competition=world["men_comp"], target_jumper=world["men"][0])


@pytest.mark.django_db
def test_jumper_affected_only_once_per_competition(world):
    use(world, 0, b.WIND, competition=world["men_comp"], target_jumper=world["men"][2])
    errors = errors_of(
        world, 1, b.BLACKLIST, competition=world["men_comp"], target_jumper=world["men"][2]
    )
    assert any("już objęty innym bonusem" in e for e in errors)


@pytest.mark.django_db
def test_competition_bonus_requires_competition_of_that_weekend(world):
    assert "Wskaż konkurs." in errors_of(world, 0, b.WIND, target_jumper=world["men"][0])
    other = Weekend.objects.create(name="Inny", start_date=timezone.now().date())
    foreign = Competition.objects.create(
        weekend=other, name="X", gender="M", start_at=timezone.now() + timedelta(days=9)
    )
    assert (
        "nie należy do wybranego weekendu"
        in errors_of(world, 0, b.WIND, competition=foreign, target_jumper=world["men"][0])[0]
    )


@pytest.mark.django_db
def test_patriot_only_for_poles(world):
    use(world, 0, b.PATRIOT, competition=world["men_comp"], target_jumper=world["men"][0])
    assert (
        "tylko na Polaka"
        in errors_of(
            world, 1, b.PATRIOT, competition=world["men_comp"], target_jumper=world["men"][1]
        )[0]
    )


@pytest.mark.django_db
def test_steal_ownership_gender_and_not_self(world):
    g1, g2 = world["players"][0], world["players"][1]
    created = use(
        world,
        0,
        b.STEAL,
        competition=world["men_comp"],
        target_player=g2,
        target_jumper=world["men"][2],
        give_jumper=world["men"][0],
    )
    assert created.target_player == g2

    wrong_owner = errors_of(
        world,
        2,
        b.STEAL,
        competition=world["men_comp"],
        target_player=g2,
        target_jumper=world["men"][0],  # należy do G1, nie do G2
        give_jumper=world["men"][4],
    )
    assert any("musi należeć do wskazanego gracza" in e for e in wrong_owner)

    wrong_gender = errors_of(
        world,
        0,
        b.STEAL,
        competition=world["women_comp"],
        target_player=g2,
        target_jumper=world["women"][0],
        give_jumper=world["men"][1],
    )
    assert any("tej samej płci" in e for e in wrong_gender)
    assert g1  # użyte, by nie zgłaszać nieużywanej zmiennej


@pytest.mark.django_db
def test_duel_and_reversed_target_players_and_norway_protection(world):
    use(world, 1, b.NORWAY)  # G2 ma Norwega
    assert "ma Norwega" in errors_of(world, 0, b.DUEL, target_player=world["players"][1])[0]
    use(world, 0, b.DUEL, target_player=world["players"][2])  # inny cel - można


@pytest.mark.django_db
def test_typer_picks_five_men_in_men_competition_only(world):
    men = world["men"]
    created = use(world, 0, b.TYPER, competition=world["men_comp"], picks=men[:5])
    assert created.picks == [j.pk for j in men[:5]]
    assert (
        "tylko w konkursach mężczyzn"
        in errors_of(world, 1, b.TYPER, competition=world["women_comp"], picks=men[:5])[0]
    )
    assert any(
        "tylko mężczyzn" in e
        for e in errors_of(
            world, 1, b.TYPER, competition=world["men_comp"], picks=[*men[:4], world["women"][0]]
        )
    )
    assert any(
        "5 różnych" in e
        for e in errors_of(world, 2, b.TYPER, competition=world["men_comp"], picks=men[:3])
    )


@pytest.mark.django_db
def test_dream_team_needs_five_men_and_one_woman(world):
    picks = [*world["men"][5:10], world["women"][1]]
    use(world, 0, b.DREAM_TEAM, competition=world["men_comp"], picks=picks)
    assert any(
        "5 skoczków i 1 skoczkini" in e
        for e in errors_of(
            world, 1, b.DREAM_TEAM, competition=world["men_comp"], picks=world["men"][5:11]
        )
    )


@pytest.mark.django_db
def test_weekend_bonus_cannot_have_competition_and_one_per_scope(world):
    use(world, 0, b.NORWAY)
    errors = errors_of(world, 0, b.REVERSED, target_player=world["players"][0])
    assert any("już odpalony bonus" in e for e in errors)  # drugi bonus weekendowy
    # ale bonus konkursowy obok weekendowego jest dozwolony
    use(world, 0, b.WIND, competition=world["men_comp"], target_jumper=world["men"][0])


@pytest.mark.django_db
def test_pilich_not_available_yet(world):
    assert "nie jest jeszcze dostępny" in errors_of(world, 0, b.PILICH)[0]


@pytest.mark.django_db
def test_bonuses_lock_when_competition_or_weekend_starts(world):
    world["men_comp"].start_at = timezone.now() - timedelta(hours=1)
    world["men_comp"].save()
    assert (
        "Za późno"
        in errors_of(
            world, 0, b.WIND, competition=world["men_comp"], target_jumper=world["men"][0]
        )[0]
    )
    assert "Za późno" in errors_of(world, 0, b.NORWAY)[0]  # weekend też już ruszył
    # konkurs kobiet jeszcze się nie zaczął
    use(world, 0, b.WIND, competition=world["women_comp"], target_jumper=world["women"][0])
    # admin może obejść blokadę
    use(world, 1, b.NORWAY, override=True)


@pytest.mark.django_db
def test_season_limit_and_typer_three_times(world):
    other = Competition.objects.create(
        weekend=world["weekend"],
        name="M2",
        gender="M",
        start_at=timezone.now() + timedelta(days=3),
        external_id="3",
    )
    use(world, 0, b.WIND, competition=world["men_comp"], target_jumper=world["men"][0])
    assert any(
        "Limit użyć" in e
        for e in errors_of(world, 0, b.WIND, competition=other, target_jumper=world["men"][1])
    )


# --- Cofanie, opis, wpływ na punkty -------------------------------------------------------------


@pytest.mark.django_db
def test_cancel_before_start_restores_availability(world):
    created = use(world, 0, b.WIND, competition=world["men_comp"], target_jumper=world["men"][0])
    services.cancel_bonus(created)
    assert BonusUse.objects.count() == 0
    use(world, 0, b.WIND, competition=world["men_comp"], target_jumper=world["men"][1])


@pytest.mark.django_db
def test_cancel_after_start_rejected_unless_admin(world):
    created = use(world, 0, b.WIND, competition=world["men_comp"], target_jumper=world["men"][0])
    world["men_comp"].start_at = timezone.now() - timedelta(minutes=1)
    world["men_comp"].save()
    created.refresh_from_db()
    with pytest.raises(services.BonusError):
        services.cancel_bonus(created)
    services.cancel_bonus(created, override=True)
    assert BonusUse.objects.count() == 0


@pytest.mark.django_db
def test_used_bonus_changes_weekend_points(world):
    use(world, 0, b.DOUBLE_CAPTAIN, competition=world["men_comp"], target_jumper=world["men"][0])
    Result.objects.create(competition=world["men_comp"], jumper=world["men"][0], rank=1)
    score = services.weekend_scores(world["weekend"])[world["players"][0].pk]
    assert score.total == 100 + 10  # x2 kapitan + premia za weekend


@pytest.mark.django_db
def test_describe_hides_secret_picks(world):
    created = use(world, 0, b.TYPER, competition=world["men_comp"], picks=world["men"][:5])
    assert "wybór ukryty" in services.describe_bonus(created, hide_secret=True)
    assert "M1" in services.describe_bonus(created)


# --- Widoki -------------------------------------------------------------------------------------


def login(client, user):
    client.login(username=user.username, password="haslo-12345")


def post_use(client, world, player_index, code, **fields):
    return client.post(
        reverse("bonus_use", args=[world["weekend"].pk]),
        {"player": world["players"][player_index].pk, "code": code, **fields},
        follow=True,
    )


@pytest.mark.django_db
def test_bonus_page_requires_login_and_renders(client, world):
    assert client.get(reverse("bonuses")).status_code == 302
    login(client, world["users"][0])
    html = client.get(reverse("bonuses")).content.decode()
    assert "Odpal bonus" in html
    assert 'value="pilich"' not in html  # jeszcze niedostępny w formularzu
    assert "Podwójny kapitan" in html


@pytest.mark.django_db
def test_use_bonus_via_view_and_see_it_listed(client, world):
    login(client, world["users"][0])
    response = post_use(
        client,
        world,
        0,
        b.DOUBLE_CAPTAIN,
        competition=world["men_comp"].pk,
        tj=world["men"][0].pk,
    )
    html = response.content.decode()
    assert "G1 odpala: Podwójny kapitan." in html
    assert BonusUse.objects.get().made_by == world["users"][0]


@pytest.mark.django_db
def test_view_shows_validation_errors(client, world):
    login(client, world["users"][0])
    html = post_use(client, world, 0, b.WIND, competition=world["men_comp"].pk).content.decode()
    assert "Wskaż zawodnika." in html
    assert BonusUse.objects.count() == 0


@pytest.mark.django_db
def test_steal_via_view_uses_separate_fields(client, world):
    login(client, world["users"][0])
    post_use(
        client,
        world,
        0,
        b.STEAL,
        competition=world["men_comp"].pk,
        tp=world["players"][1].pk,
        sj=world["men"][2].pk,
        gj=world["men"][0].pk,
    )
    steal = BonusUse.objects.get()
    assert (steal.target_jumper, steal.give_jumper) == (world["men"][2], world["men"][0])


@pytest.mark.django_db
def test_typer_picks_are_hidden_from_other_players_until_start(client, world):
    login(client, world["users"][0])
    fields = {f"t{i + 1}": world["men"][5 + i].pk for i in range(5)}
    post_use(client, world, 0, b.TYPER, competition=world["men_comp"].pk, **fields)

    html_owner = client.get(reverse("bonuses")).content.decode()
    assert "M6, M7" in html_owner  # właściciel widzi swój wybór

    login(client, world["users"][1])
    html_other = client.get(reverse("bonuses")).content.decode()
    assert "wybór ukryty do startu konkursu" in html_other
    assert "M6, M7" not in html_other

    world["men_comp"].start_at = timezone.now() - timedelta(minutes=5)
    world["men_comp"].save()
    html_after = client.get(reverse("bonuses")).content.decode()
    assert "M6, M7" in html_after


@pytest.mark.django_db
def test_cancel_via_view(client, world):
    login(client, world["users"][0])
    post_use(client, world, 0, b.NORWAY)
    bonus = BonusUse.objects.get()
    assert client.get(reverse("bonus_cancel", args=[bonus.pk])).status_code == 405
    response = client.post(reverse("bonus_cancel", args=[bonus.pk]), follow=True)
    assert "Bonus cofnięty." in response.content.decode()
    assert BonusUse.objects.count() == 0


@pytest.mark.django_db
def test_regular_user_cannot_override_lock(client, world):
    world["men_comp"].start_at = timezone.now() - timedelta(hours=1)
    world["men_comp"].save()
    login(client, world["users"][0])
    html = post_use(client, world, 0, b.NORWAY, override="1").content.decode()
    assert "Za późno" in html
    assert BonusUse.objects.count() == 0
