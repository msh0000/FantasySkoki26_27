"""Warstwa łącząca bazę danych (modele) z czystą logiką z rules.py i scoring.py."""

from collections import defaultdict
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from . import bonuses, rules, scoring
from .bonuses import SPECS, Scope
from .models import (
    Adjustment,
    BonusUse,
    Competition,
    Jumper,
    Player,
    QueueSlot,
    Result,
    RosterEntry,
    Transfer,
    Weekend,
)


class TransferError(Exception):
    pass


# --- Składy ---------------------------------------------------------------------------------


def snapshot_rosters(competition: Competition) -> None:
    """Zamraża aktualne składy graczy na dany konkurs (wywołujemy przed startem konkursu)."""
    with transaction.atomic():
        competition.rosters.all().delete()
        RosterEntry.objects.bulk_create(
            RosterEntry(competition=competition, player_id=j.owner_id, jumper=j)
            for j in Jumper.objects.filter(owner__isnull=False)
        )
        competition.roster_locked = True
        competition.save(update_fields=["roster_locked"])


def lock_started_competitions(now=None) -> int:
    """Zamraża składy konkursów, które już ruszyły, a jeszcze nie mają zrzutu.

    Dzięki temu późniejsze transfery nie zmienią wstecz punktów starych konkursów. Wywołujemy to
    przed każdą zmianą składów i przy liczeniu punktów (nie mamy harmonogramu na serwerze).
    """
    locked = 0
    for competition in Competition.objects.filter(
        roster_locked=False, start_at__lte=now or timezone.now()
    ):
        snapshot_rosters(competition)
        locked += 1
    return locked


def competition_rosters(competition: Competition) -> dict[int, list[int]]:
    if not competition.roster_locked and competition.is_locked():
        snapshot_rosters(competition)
    rosters: dict[int, list[int]] = defaultdict(list)
    if competition.roster_locked:
        for entry in competition.rosters.all():
            rosters[entry.player_id].append(entry.jumper_id)
    else:
        for j in Jumper.objects.filter(owner__isnull=False):
            rosters[j.owner_id].append(j.id)
    return rosters


# --- Punkty ---------------------------------------------------------------------------------


def _jumper_infos() -> dict[int, scoring.JumperInfo]:
    return {
        j.id: scoring.JumperInfo(gender=j.gender, country=j.country, name=j.name)
        for j in Jumper.objects.all()
    }


def weekend_scores(weekend: Weekend) -> dict[int, scoring.PlayerScore]:
    players = list(Player.objects.values_list("id", flat=True))
    competitions = []
    for comp in weekend.competitions.filter(counts=True):
        ranks = {r.jumper_id: r.rank for r in Result.objects.filter(competition=comp) if r.rank}
        if not ranks:
            continue
        competitions.append(
            scoring.CompetitionInput(
                label=comp.name,
                series=comp.series,
                gender=comp.gender,
                ranks=ranks,
                rosters=dict(competition_rosters(comp)),
                bonuses=[b.to_bonus() for b in comp.bonus_uses.all()],
            )
        )
    weekend_bonuses = [
        b.to_bonus()
        for b in weekend.bonus_uses.filter(competition__isnull=True)
        if SPECS[b.code].scope is Scope.WEEKEND
    ]
    transfer_counts = {
        row["player"]: row["n"]
        for row in weekend.transfers.values("player").annotate(n=Count("id"))
    }
    adjustments = {
        row["player"]: float(row["total"])
        for row in Adjustment.objects.filter(weekend=weekend)
        .values("player")
        .annotate(total=Sum("points"))
    }
    return scoring.score_weekend(
        competitions=competitions,
        jumpers=_jumper_infos(),
        players=players,
        weekend_bonuses=weekend_bonuses,
        transfer_counts=transfer_counts,
        adjustments=adjustments,
    )


def season_standings(before: Weekend | None = None) -> dict[int, float]:
    """Suma punktów graczy z wszystkich weekendów (lub tych przed `before`)."""
    totals = {pid: 0.0 for pid in Player.objects.values_list("id", flat=True)}
    weekends = Weekend.objects.all()
    if before is not None:
        weekends = weekends.filter(start_date__lt=before.start_date)
    for weekend in weekends:
        for pid, score in weekend_scores(weekend).items():
            totals[pid] = totals.get(pid, 0.0) + score.total
    return totals


def season_overview() -> dict:
    """Ranking sezonu z przyrostem z ostatniego weekendu, w którym ktoś zdobył punkty."""
    totals = {pid: 0.0 for pid in Player.objects.values_list("id", flat=True)}
    last_weekend = None
    last_scores: dict[int, float] = {}
    for weekend in Weekend.objects.all():
        scores = weekend_scores(weekend)
        for pid, score in scores.items():
            totals[pid] = totals.get(pid, 0.0) + score.total
        if any(score.total for score in scores.values()):
            last_weekend = weekend
            last_scores = {pid: score.total for pid, score in scores.items()}
    return {"totals": totals, "last_weekend": last_weekend, "last_scores": last_scores}


# --- Kolejka transferów ---------------------------------------------------------------------


def build_queue(weekend: Weekend) -> list[QueueSlot]:
    """Tworzy kolejkę transferów wg rankingu sprzed tego weekendu (od ostatniego do pierwszego)."""
    if weekend.queue.exists():
        return list(weekend.queue.all())
    standings = season_standings(before=weekend)
    tiebreak = dict(Player.objects.values_list("id", "order"))
    order = rules.queue_order(standings, tiebreak)
    return QueueSlot.objects.bulk_create(
        QueueSlot(weekend=weekend, player_id=pid, position=i) for i, pid in enumerate(order, 1)
    )


def _queue_state(weekend: Weekend) -> tuple[list[int], set[int]]:
    slots = list(weekend.queue.all())
    queue = [s.player_id for s in slots]
    resolved = {s.player_id for s in slots if s.status != QueueSlot.PENDING}
    return queue, resolved


def can_transfer(weekend: Weekend, player: Player) -> bool:
    queue, resolved = _queue_state(weekend)
    return rules.can_act_in_queue(queue, resolved, player.id)


def players_to_confirm_skip(weekend: Weekend, player: Player) -> list[Player]:
    queue, resolved = _queue_state(weekend)
    ids = rules.players_to_confirm_skip(queue, resolved, player.id)
    players = {p.id: p for p in Player.objects.filter(id__in=ids)}
    return [players[i] for i in ids]


def finish_turn(weekend: Weekend, player: Player) -> None:
    """Kończy turę gracza w kolejce i oddaje pałeczkę dalej.

    Status to "zrobił transfer", jeśli gracz wykonał choć jeden transfer w tym weekendzie,
    a w przeciwnym razie "pominął". W swojej turze gracz może zrobić dowolnie wiele transferów
    (kolejne ponad pierwszy kosztują punkty), a turę kończy dopiero ten krok.
    """
    slot = weekend.queue.filter(player=player).first()
    if slot and slot.status == QueueSlot.PENDING:
        made = weekend.transfers.filter(player=player).exists()
        slot.status = QueueSlot.DONE if made else QueueSlot.SKIPPED
        slot.save(update_fields=["status"])


@transaction.atomic
def make_transfer(
    weekend: Weekend,
    player: Player,
    out_jumper: Jumper,
    in_jumper: Jumper,
    *,
    made_by=None,
    enforce_queue: bool = True,
    enforce_lock: bool = True,
    now=None,
) -> Transfer:
    """Zamiana 1 za 1: oddajesz swojego zawodnika, bierzesz wolnego z puli."""
    if enforce_lock and weekend.is_locked(now or timezone.now()):
        raise TransferError("Weekend już się rozpoczął - transfery są zablokowane.")
    if out_jumper.owner_id != player.id:
        raise TransferError("Oddawany zawodnik nie należy do tego gracza.")
    if in_jumper.owner_id is not None:
        raise TransferError("Wybrany zawodnik ma już właściciela.")
    if not in_jumper.active:
        raise TransferError("Ten zawodnik nie należy do puli dostępnych zawodników.")
    if out_jumper.gender != in_jumper.gender:
        raise TransferError("Można zamienić tylko zawodnika na zawodnika tej samej płci.")
    if enforce_queue and not can_transfer(weekend, player):
        raise TransferError("To jeszcze nie Twoja kolej w kolejce transferów.")

    lock_started_competitions(now)
    out_jumper.owner = None
    out_jumper.save(update_fields=["owner"])
    in_jumper.owner = player
    in_jumper.save(update_fields=["owner"])
    return Transfer.objects.create(
        weekend=weekend, player=player, out_jumper=out_jumper, in_jumper=in_jumper, made_by=made_by
    )


# --- Draft (przypisanie drużyn) ---------------------------------------------------------------


def draft_conflicts(selection: dict[Player, list[Jumper]]) -> list[str]:
    """Zawodnicy wybrani przez więcej niż jednego gracza lub wielokrotnie przez jednego."""
    chosen_by: dict[int, tuple[Jumper, list[str]]] = {}
    for player, jumpers in selection.items():
        for jumper in jumpers:
            chosen_by.setdefault(jumper.id, (jumper, []))[1].append(player.name)
    return [
        f"{jumper.name} jest wybrany więcej niż raz ({', '.join(names)})."
        for jumper, names in chosen_by.values()
        if len(names) > 1
    ]


@transaction.atomic
def assign_rosters(selection: dict[Player, list[Jumper]]) -> None:
    """Ustawia składy podanych graczy (zastępuje ich dotychczasowe)."""
    lock_started_competitions()
    Jumper.objects.filter(owner__in=list(selection)).update(owner=None)
    for player, jumpers in selection.items():
        Jumper.objects.filter(id__in=[j.id for j in jumpers]).update(owner=player)


# --- Okno bonusowe i przegląd bonusów gracza --------------------------------------------------


@dataclass
class BonusWindow:
    """Dla którego konkursu i weekendu można teraz odpalać bonusy.

    Zawsze jest to najbliższy konkurs, który się jeszcze nie rozpoczął, a bonusy odblokowują się
    dopiero, gdy poprzedni konkurs (weekend) się zakończył, czyli ma wczytane wyniki.
    Błąd (niepusty tekst) oznacza, że dany rodzaj bonusów jest teraz zablokowany.
    """

    competition: Competition | None = None
    weekend: Weekend | None = None
    competition_error: str = ""
    weekend_error: str = ""


def bonus_window(now=None) -> BonusWindow:
    now = now or timezone.now()
    competitions = list(
        Competition.objects.filter(counts=True).select_related("weekend").order_by("start_at", "id")
    )
    nearest = next((c for c in competitions if c.start_at > now), None)
    if nearest is None:
        message = "Brak nadchodzących konkursów."
        return BonusWindow(competition_error=message, weekend_error=message)

    finished = set(
        Result.objects.filter(competition__in=competitions)
        .values_list("competition_id", flat=True)
        .distinct()
    )
    position = competitions.index(nearest)
    previous = competitions[position - 1] if position else None

    competition_error = ""
    if previous is not None and previous.pk not in finished:
        competition_error = (
            f"Poprzedni konkurs ({previous.name}) jeszcze się nie zakończył - "
            "bonusy odblokują się po wczytaniu jego wyników."
        )

    weekend = nearest.weekend
    weekend_error = ""
    if weekend.is_locked(now):
        weekend_error = "Weekend już się rozpoczął - bonusy weekendowe są zablokowane."
    else:
        unfinished = [c for c in competitions[:position] if c.pk not in finished]
        if unfinished:
            weekend_error = (
                f"Poprzedni weekend jeszcze się nie zakończył ({unfinished[0].name}) - "
                "bonusy odblokują się po wczytaniu wyników."
            )
    return BonusWindow(nearest, weekend, competition_error, weekend_error)


def bonus_overview(player: Player, window: BonusWindow | None = None) -> list[dict]:
    """Dla każdego z 11 bonusów: ile razy użyty, limit i czy można go teraz odpalić."""
    window = window or bonus_window()
    used: dict[str, int] = {}
    for code in player.bonus_uses.values_list("code", flat=True):
        used[code] = used.get(code, 0) + 1
    overview = []
    for spec in SPECS.values():
        count = used.get(spec.code, 0)
        if count >= spec.season_limit:
            reason = "wykorzystany"
        elif spec.code == bonuses.PILICH:
            reason = "wkrótce"
        elif spec.scope is Scope.WEEKEND:
            reason = window.weekend_error
        else:
            reason = window.competition_error
        overview.append(
            {
                "code": spec.code,
                "label": spec.label,
                "scope": "weekend" if spec.scope is Scope.WEEKEND else "konkurs",
                "used": count,
                "limit": spec.season_limit,
                "remaining": spec.season_limit - count,
                "available": not reason,
                "reason": reason,
            }
        )
    return overview


# --- Okno transferowe (pomocnicze dla ekranów) ---------------------------------------------------


def current_transfer_weekend() -> Weekend | None:
    """Najbliższy weekend, który jeszcze się nie rozpoczął (a gdy brak - ostatni)."""
    weekends = list(Weekend.objects.all())
    for weekend in weekends:
        if not weekend.is_locked():
            return weekend
    return weekends[-1] if weekends else None


def transfers_made(weekend: Weekend) -> dict[int, int]:
    """Liczba transferów każdego gracza w weekendzie (do kary za kolejne)."""
    return {
        row["player"]: row["n"]
        for row in weekend.transfers.values("player").annotate(n=Count("id"))
    }


# --- Bonusy ---------------------------------------------------------------------------------


class BonusError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _gender_fits(competition: Competition, jumper: Jumper) -> bool:
    return competition.gender == rules.MIXED or competition.gender == jumper.gender


def use_bonus(
    *,
    player: Player,
    code: str,
    target_player: Player | None = None,
    target_jumper: Jumper | None = None,
    give_jumper: Jumper | None = None,
    picks: list[Jumper] | None = None,
    made_by=None,
    now=None,
) -> BonusUse:
    """Odpala bonus gracza na najbliższy konkurs/weekend. Błąd: BonusError z listą komunikatów."""
    spec = SPECS[code]
    picks = picks or []
    errors: list[str] = []

    if code == bonuses.PILICH:
        raise BonusError(["Bonus „Tomasz Pilich” nie jest jeszcze dostępny w aplikacji."])

    window = bonus_window(now)
    if spec.scope is Scope.COMPETITION:
        competition, weekend = (
            window.competition,
            (window.competition.weekend if window.competition else None),
        )
        problem = window.competition_error
    else:
        competition, weekend = None, window.weekend
        problem = window.weekend_error
    if problem:
        raise BonusError([problem])

    if code in bonuses.JUMPER_TARGETING:
        if target_jumper is None:
            errors.append("Wskaż zawodnika.")
        elif competition and not _gender_fits(competition, target_jumper):
            errors.append("Ten zawodnik nie startuje w tym konkursie (zła płeć).")
        elif (
            code in (bonuses.DOUBLE_CAPTAIN, bonuses.WIND, bonuses.BLACKLIST)
            and target_jumper.owner_id is None
        ):
            errors.append("Ten bonus działa na zawodnika, który jest w czyjejś drużynie.")
        elif code == bonuses.PATRIOT and target_jumper.country != "POL":
            errors.append("Patriota działa tylko na Polaka.")

    if code == bonuses.STEAL and target_jumper and give_jumper:
        if target_player is None or target_jumper.owner_id != target_player.pk:
            errors.append("Zawodnik, którego bierzesz, musi należeć do wskazanego gracza.")
        if give_jumper.owner_id != player.pk:
            errors.append("Zawodnik, którego oddajesz, musi należeć do Ciebie.")
        if give_jumper.gender != target_jumper.gender:
            errors.append("Wymiana tylko zawodnika za zawodnika tej samej płci.")
        if competition and not _gender_fits(competition, target_jumper):
            errors.append("Ci zawodnicy nie startują w tym konkursie (zła płeć).")

    if code == bonuses.TYPER:
        if competition and competition.gender == rules.FEMALE:
            errors.append("Typer działa tylko w konkursach mężczyzn (także mieszanych).")
        if any(j.gender != rules.MALE for j in picks):
            errors.append("W typerze wybierasz tylko mężczyzn.")

    if code == bonuses.DREAM_TEAM:
        men = sum(1 for j in picks if j.gender == rules.MALE)
        if len(picks) == 6 and men != 5:
            errors.append("Drużyna marzeń: dokładnie 5 skoczków i 1 skoczkini.")

    use = BonusUse(
        player=player,
        code=code,
        weekend=weekend,
        competition=competition,
        target_player=(
            target_player if code in bonuses.PLAYER_TARGETING or code == bonuses.STEAL else None
        ),
        target_jumper=target_jumper,
        give_jumper=give_jumper if code == bonuses.STEAL else None,
        picks=[j.pk for j in picks] if code in (bonuses.TYPER, bonuses.DREAM_TEAM) else [],
        made_by=made_by,
    )
    try:
        use.full_clean()
    except ValidationError as error:
        errors.extend(error.messages)
    if errors:
        raise BonusError(list(dict.fromkeys(errors)))
    use.save()
    return use


def cancel_bonus(use: BonusUse, *, override: bool = False, now=None) -> None:
    """Cofa użycie bonusu (tylko przed startem konkursu/weekendu, chyba że tryb admina)."""
    spec = SPECS[use.code]
    locked = (
        use.competition.is_locked(now)
        if spec.scope is Scope.COMPETITION and use.competition
        else use.weekend.is_locked(now)
    )
    if locked and not override:
        raise BonusError(["Za późno na cofnięcie - konkurs lub weekend już się rozpoczął."])
    use.delete()


def bonus_is_locked(use: BonusUse, now=None) -> bool:
    spec = SPECS[use.code]
    if spec.scope is Scope.COMPETITION and use.competition:
        return use.competition.is_locked(now)
    return use.weekend.is_locked(now)


def describe_bonus(use: BonusUse, *, hide_secret: bool = False) -> str:
    """Opis użycia bonusu (cel, zawodnicy). Wybory typera i drużyny marzeń można ukryć."""
    parts: list[str] = []
    if use.competition:
        parts.append(use.competition.name)
    if use.target_player:
        parts.append(f"na: {use.target_player.name}")
    if use.code == bonuses.STEAL and use.target_jumper and use.give_jumper:
        parts.append(f"bierze {use.target_jumper.name}, oddaje {use.give_jumper.name}")
    elif use.target_jumper:
        parts.append(use.target_jumper.name)
    if use.picks:
        if hide_secret:
            parts.append("wybór ukryty do startu konkursu")
        else:
            names = {j.pk: j.name for j in Jumper.objects.filter(pk__in=use.picks)}
            parts.append(", ".join(names.get(pk, "?") for pk in use.picks))
    return " · ".join(parts)
