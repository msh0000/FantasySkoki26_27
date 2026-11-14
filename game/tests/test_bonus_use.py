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
        Jumper.objects.create(name=f"M{i}", country="POL" if i in (1, 6) else "AUT", gender="M")
        for i in range(1, 13)
    ]
    women = [Jumper.objects.create(name=f"K{i}", country="SLO", gender="K") for i in range(1, 4)]
    # G1: M1(POL), M2; G2: M3, M4, K1; G3: M5
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


def finish(competition, jumper):
    """Kończy konkurs: ustawia start w przeszłości i dodaje wynik."""
    competition.start_at = timezone.now() - timedelta(hours=5)
    competition.save()
    Result.objects.create(competition=competition, jumper=jumper, rank=1)


def use(world, player_index, code, **kwargs):
    return services.use_bonus(player=world["players"][player_index], code=code, **kwargs)


def errors_of(world, player_index, code, **kwargs) -> list[str]:
    with pytest.raises(services.BonusError) as caught:
        use(world, player_index, code, **kwargs)
    return caught.value.errors


# --- Okno bonusowe: tylko najbliższy konkurs/weekend, po zakończeniu poprzedniego ----------------


@pytest.mark.django_db
def test_window_points_at_nearest_unstarted_competition(world):
    window = services.bonus_window()
    assert window.competition == world["men_comp"]
    assert window.weekend == world["weekend"]
    assert window.competition_error == window.weekend_error == ""  # to pierwszy konkurs w sezonie


@pytest.mark.django_db
def test_window_moves_to_next_competition_after_start(world):
    finish(world["men_comp"], world["men"][0])
    window = services.bonus_window()
    assert window.competition == world["women_comp"]
    assert window.competition_error == ""  # poprzedni (męski) ma wyniki
    assert "Weekend już się rozpoczął" in window.weekend_error


@pytest.mark.django_db
def test_competition_bonuses_wait_until_previous_competition_has_results(world):
    world["men_comp"].start_at = timezone.now() - timedelta(hours=2)  # ruszył, brak wyników
    world["men_comp"].save()
    window = services.bonus_window()
    assert window.competition == world["women_comp"]
    assert "jeszcze się nie zakończył" in window.competition_error
    assert (
        "jeszcze się nie zakończył"
        in errors_of(world, 1, b.WIND, target_jumper=world["women"][0])[0]
    )


@pytest.mark.django_db
def test_weekend_bonuses_wait_until_previous_weekend_finished(world):
    later = Weekend.objects.create(name="Ruka", start_date=timezone.now().date())
    Competition.objects.create(
        weekend=later,
        name="R1",
        gender="M",
        start_at=timezone.now() + timedelta(days=9),
        external_id="9",
    )
    # Lillehammer się skończył (oba konkursy z wynikami), więc najbliższy jest Ruka.
    finish(world["men_comp"], world["men"][0])
    finish(world["women_comp"], world["women"][0])
    window = services.bonus_window()
    assert window.weekend.name == "Ruka"
    assert window.weekend_error == ""
    use(world, 0, b.NORWAY)  # działa

    # Gdy w poprzednim weekendzie brakuje wyników jednego konkursu - blokada.
    Result.objects.filter(competition=world["women_comp"]).delete()
    assert "Poprzedni weekend jeszcze się nie zakończył" in services.bonus_window().weekend_error


@pytest.mark.django_db
def test_no_upcoming_competition(world):
    for comp in (world["men_comp"], world["women_comp"]):
        finish(comp, world["men"][0]) if comp.gender == "M" else None
    world["women_comp"].start_at = timezone.now() - timedelta(hours=1)
    world["women_comp"].save()
    assert "Brak nadchodzących konkursów" in errors_of(world, 0, b.NORWAY)[0]


@pytest.mark.django_db
def test_bonus_is_always_for_the_nearest_competition(world):
    created = use(world, 0, b.WIND, target_jumper=world["men"][0])
    assert created.competition == world["men_comp"]
    assert created.weekend == world["weekend"]


# --- Zasady poszczególnych bonusów ----------------------------------------------------------------


@pytest.mark.django_db
def test_double_captain_and_wind_work_on_any_jumper_in_a_team(world):
    use(world, 0, b.DOUBLE_CAPTAIN, target_jumper=world["men"][0])  # własny
    use(world, 1, b.WIND, target_jumper=world["men"][1])  # zawodnik z cudzej drużyny (G1)
    free = world["men"][10]  # wolny - nie jest w żadnej drużynie
    err = errors_of(world, 2, b.WIND, target_jumper=free)
    assert "jest w czyjejś drużynie" in err[0]


@pytest.mark.django_db
def test_jumper_gender_must_fit_competition(world):
    assert "zła płeć" in errors_of(world, 1, b.WIND, target_jumper=world["women"][0])[0]


@pytest.mark.django_db
def test_blacklist_targets_jumpers_in_teams_including_own(world):
    use(world, 0, b.BLACKLIST, target_jumper=world["men"][2])  # zawodnik G2
    free = world["men"][10]
    assert "w czyjejś drużynie" in errors_of(world, 1, b.BLACKLIST, target_jumper=free)[0]
    use(world, 1, b.BLACKLIST, target_jumper=world["men"][3])  # na siebie też wolno


@pytest.mark.django_db
def test_jumper_affected_only_once_per_competition(world):
    use(world, 0, b.BLACKLIST, target_jumper=world["men"][2])
    errors = errors_of(world, 1, b.BLACKLIST, target_jumper=world["men"][2])
    assert any("już objęty innym bonusem" in e for e in errors)


@pytest.mark.django_db
def test_patriot_only_for_poles_free_or_owned(world):
    use(world, 0, b.PATRIOT, target_jumper=world["men"][5])  # wolny Polak
    assert "tylko na Polaka" in errors_of(world, 1, b.PATRIOT, target_jumper=world["men"][1])[0]


@pytest.mark.django_db
def test_steal_ownership_gender_and_not_self(world):
    g2 = world["players"][1]
    created = use(
        world,
        0,
        b.STEAL,
        target_player=g2,
        target_jumper=world["men"][2],
        give_jumper=world["men"][0],
    )
    assert created.target_player == g2

    wrong_owner = errors_of(
        world,
        2,
        b.STEAL,
        target_player=g2,
        target_jumper=world["men"][0],  # należy do G1, nie do G2
        give_jumper=world["men"][4],
    )
    assert any("musi należeć do wskazanego gracza" in e for e in wrong_owner)

    not_mine = errors_of(
        world,
        1,
        b.STEAL,
        target_player=world["players"][0],
        target_jumper=world["men"][1],
        give_jumper=world["men"][0],  # nie jest zawodnikiem G2
    )
    assert any("musi należeć do Ciebie" in e for e in not_mine)


@pytest.mark.django_db
def test_duel_and_reversed_and_norway_protection(world):
    use(world, 1, b.NORWAY)  # G2 ma Norwega
    assert "ma Norwega" in errors_of(world, 0, b.DUEL, target_player=world["players"][1])[0]
    use(world, 0, b.DUEL, target_player=world["players"][2])  # inny cel można
    assert any("sobie" in e for e in errors_of(world, 2, b.DUEL, target_player=world["players"][2]))


@pytest.mark.django_db
def test_typer_only_in_men_competition_with_five_men(world):
    men = world["men"]
    created = use(world, 0, b.TYPER, picks=men[:5])
    assert created.picks == [j.pk for j in men[:5]]
    assert any(
        "tylko mężczyzn" in e
        for e in errors_of(world, 1, b.TYPER, picks=[*men[:4], world["women"][0]])
    )
    assert any("5 różnych" in e for e in errors_of(world, 2, b.TYPER, picks=men[:3]))


@pytest.mark.django_db
def test_typer_rejected_when_nearest_competition_is_women(world):
    finish(world["men_comp"], world["men"][0])  # najbliższy to teraz konkurs kobiet
    assert "tylko w konkursach mężczyzn" in errors_of(world, 0, b.TYPER, picks=world["men"][:5])[0]


@pytest.mark.django_db
def test_dream_team_needs_five_men_and_one_woman(world):
    use(world, 0, b.DREAM_TEAM, picks=[*world["men"][5:10], world["women"][1]])
    assert any(
        "5 skoczków i 1 skoczkini" in e
        for e in errors_of(world, 1, b.DREAM_TEAM, picks=world["men"][5:11])
    )


@pytest.mark.django_db
def test_only_one_bonus_per_scope_and_season_limits(world):
    use(world, 0, b.NORWAY)
    assert any(
        "już odpalony bonus" in e
        for e in errors_of(world, 0, b.REVERSED, target_player=world["players"][0])
    )
    use(world, 0, b.WIND, target_jumper=world["men"][0])  # konkursowy obok weekendowego - można

    finish(world["men_comp"], world["men"][0])
    finish_second = world["women_comp"]
    finish_second.start_at = timezone.now() - timedelta(hours=1)
    finish_second.save()
    Result.objects.create(competition=finish_second, jumper=world["women"][0], rank=1)
    later = Competition.objects.create(
        weekend=Weekend.objects.create(name="Ruka", start_date=timezone.now().date()),
        name="R1",
        gender="M",
        start_at=timezone.now() + timedelta(days=9),
        external_id="9",
    )
    assert later.pk
    assert any(
        "Limit użyć" in e for e in errors_of(world, 0, b.WIND, target_jumper=world["men"][1])
    )


@pytest.mark.django_db
def test_pilich_not_available_yet(world):
    assert "nie jest jeszcze dostępny" in errors_of(world, 0, b.PILICH)[0]


@pytest.mark.django_db
def test_overview_explains_why_bonus_is_blocked(world):
    world["men_comp"].start_at = timezone.now() - timedelta(hours=2)
    world["men_comp"].save()
    rows = {r["code"]: r for r in services.bonus_overview(world["players"][0])}
    assert rows[b.WIND]["available"] is False
    assert "jeszcze się nie zakończył" in rows[b.WIND]["reason"]
    assert rows[b.PILICH]["reason"] == "wkrótce"


# --- Cofanie, opis, wpływ na punkty -------------------------------------------------------------


@pytest.mark.django_db
def test_cancel_before_start_restores_availability(world):
    created = use(world, 0, b.WIND, target_jumper=world["men"][0])
    services.cancel_bonus(created)
    assert BonusUse.objects.count() == 0
    use(world, 0, b.WIND, target_jumper=world["men"][1])


@pytest.mark.django_db
def test_cancel_after_start_rejected(world):
    created = use(world, 0, b.WIND, target_jumper=world["men"][0])
    world["men_comp"].start_at = timezone.now() - timedelta(minutes=1)
    world["men_comp"].save()
    created.refresh_from_db()
    with pytest.raises(services.BonusError):
        services.cancel_bonus(created)


@pytest.mark.django_db
def test_used_bonus_changes_weekend_points(world):
    created = use(world, 0, b.DOUBLE_CAPTAIN, target_jumper=world["men"][0])
    Result.objects.create(competition=world["men_comp"], jumper=world["men"][0], rank=1)
    assert created.competition == world["men_comp"]
    score = services.weekend_scores(world["weekend"])[world["players"][0].pk]
    assert score.total == 100 + 10  # x2 kapitan + premia za weekend


@pytest.mark.django_db
def test_describe_hides_secret_picks(world):
    created = use(world, 0, b.TYPER, picks=world["men"][:5])
    assert "wybór ukryty" in services.describe_bonus(created, hide_secret=True)
    assert "M1" in services.describe_bonus(created)


# --- Widoki: wszystko z "Moja drużyna", tylko własne bonusy ----------------------------


def login(client, user):
    client.login(username=user.username, password="haslo-12345")


def post_use(client, code, **fields):
    return client.post(reverse("bonus_use"), {"code": code, **fields}, follow=True)


@pytest.mark.django_db
def test_bonus_form_only_on_my_own_team_page(client, world):
    login(client, world["users"][0])
    mine = client.get(reverse("team")).content.decode()
    assert 'id="bonus-form"' in mine
    assert 'name="player"' not in mine  # nie ma wyboru gracza - tylko swoje bonusy
    others = client.get(reverse("team_of", args=[world["players"][1].pk])).content.decode()
    assert 'id="bonus-form"' not in others
    assert "Bonusy gracza G2" in others


@pytest.mark.django_db
def test_form_shows_nearest_competition_and_has_no_competition_picker(client, world):
    login(client, world["users"][0])
    html = client.get(reverse("team")).content.decode()
    assert "najbliższego konkursu" in html
    assert "M1" in html
    assert 'name="competition"' not in html
    assert 'name="weekend"' not in html


@pytest.mark.django_db
def test_form_lists_only_relevant_jumpers(client, world):
    login(client, world["users"][0])  # G1: M1(POL), M2
    html = client.get(reverse("team")).content.decode()
    assert 'name="tj"' not in html  # nie ma już listy tylko własnych zawodników
    picker = html.split('name="sj"')[1].split("</select>")[0]
    assert 'data-owner="' in picker  # lista zawodników filtrowana wg wybranego gracza
    assert "M1" in picker and "M3" in picker  # zawodnicy z różnych drużyn (G1 i G2)
    assert "K1" not in picker  # zła płeć dla konkursu mężczyzn
    assert "M11" not in picker  # wolny zawodnik nie jest w żadnej drużynie
    poles = html.split('name="pj"')[1].split("</select>")[0]
    assert "M1" in poles and "M6" in poles
    assert "M2" not in poles  # nie-Polak
    give = html.split('name="gj"')[1].split("</select>")[0]
    assert "M1" in give and "M3" not in give


@pytest.mark.django_db
def test_use_bonus_via_view_as_myself(client, world):
    login(client, world["users"][0])
    html = post_use(
        client, b.DOUBLE_CAPTAIN, tp=world["players"][0].pk, sj=world["men"][0].pk
    ).content.decode()
    assert "Odpalono: Podwójny kapitan (M1)." in html
    use_row = BonusUse.objects.get()
    assert use_row.player == world["players"][0]
    assert use_row.made_by == world["users"][0]


@pytest.mark.django_db
def test_view_ignores_attempt_to_act_for_someone_else(client, world):
    login(client, world["users"][0])
    post_use(client, b.NORWAY, player=world["players"][1].pk)  # pole "player" jest ignorowane
    assert BonusUse.objects.get().player == world["players"][0]


@pytest.mark.django_db
def test_view_shows_validation_errors(client, world):
    login(client, world["users"][0])
    html = post_use(client, b.WIND).content.decode()
    assert "Wskaż zawodnika." in html
    assert BonusUse.objects.count() == 0


@pytest.mark.django_db
def test_steal_and_blacklist_via_view_use_player_scoped_fields(client, world):
    login(client, world["users"][0])
    post_use(
        client,
        b.STEAL,
        tp=world["players"][1].pk,
        sj=world["men"][2].pk,
        gj=world["men"][0].pk,
    )
    steal = BonusUse.objects.get()
    assert (steal.target_jumper, steal.give_jumper) == (world["men"][2], world["men"][0])
    login(client, world["users"][2])
    post_use(client, b.BLACKLIST, tp=world["players"][1].pk, sj=world["men"][3].pk)
    assert BonusUse.objects.get(code=b.BLACKLIST).target_jumper == world["men"][3]


@pytest.mark.django_db
def test_blocked_bonus_shows_reason_in_view(client, world):
    world["men_comp"].start_at = timezone.now() - timedelta(hours=2)
    world["men_comp"].save()
    login(client, world["users"][0])
    html = client.get(reverse("team")).content.decode()
    assert "jeszcze się nie zakończył" in html
    assert "Teraz nie możesz odpalić żadnego bonusu" in html or 'id="bonus-form"' in html
    response = post_use(client, b.WIND, tp=world["players"][0].pk, sj=world["men"][0].pk)
    assert "jeszcze się nie zakończył" in response.content.decode()
    assert BonusUse.objects.count() == 0


@pytest.mark.django_db
def test_cancel_only_own_bonus(client, world):
    login(client, world["users"][0])
    post_use(client, b.NORWAY)
    bonus = BonusUse.objects.get()
    assert client.get(reverse("bonus_cancel", args=[bonus.pk])).status_code == 405
    login(client, world["users"][1])
    assert client.post(reverse("bonus_cancel", args=[bonus.pk])).status_code == 403
    login(client, world["users"][0])
    response = client.post(reverse("bonus_cancel", args=[bonus.pk]), follow=True)
    assert "Bonus cofnięty." in response.content.decode()
    assert BonusUse.objects.count() == 0


@pytest.mark.django_db
def test_no_separate_bonus_page_anymore(client, world):
    login(client, world["users"][0])
    assert client.get("/bonusy/").status_code == 404
    assert "/bonusy/" not in client.get(reverse("home")).content.decode()


@pytest.mark.django_db
def test_typer_picks_hidden_from_others_on_weekend_page_until_start(client, world):
    login(client, world["users"][0])
    fields = {f"t{i + 1}": world["men"][5 + i].pk for i in range(5)}
    post_use(client, b.TYPER, **fields)

    page = reverse("weekend_detail", args=[world["weekend"].pk])
    assert "M6, M7" in client.get(page).content.decode()  # właściciel widzi
    login(client, world["users"][1])
    other = client.get(page).content.decode()
    assert "wybór ukryty do startu konkursu" in other
    assert "M6, M7" not in other

    world["men_comp"].start_at = timezone.now() - timedelta(minutes=5)
    world["men_comp"].save()
    assert "M6, M7" in client.get(page).content.decode()


@pytest.mark.django_db
def test_double_captain_on_other_players_jumper_via_view(client, world):
    login(client, world["users"][0])
    post_use(client, b.DOUBLE_CAPTAIN, tp=world["players"][1].pk, sj=world["men"][2].pk)
    created = BonusUse.objects.get()
    assert created.player == world["players"][0]
    assert created.target_jumper == world["men"][2]  # zawodnik Bartka (G2)
