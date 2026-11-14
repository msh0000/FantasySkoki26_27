"""Warstwa łącząca bazę danych (modele) z czystą logiką z rules.py i scoring.py."""

from collections import defaultdict

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from . import rules, scoring
from .bonuses import SPECS, Scope
from .models import (
    Adjustment,
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


# --- Przegląd bonusów gracza -------------------------------------------------------------------


def bonus_overview(player: Player) -> list[dict]:
    """Dla każdego z 11 bonusów: ile razy użyty, limit i opis zasięgu."""
    used: dict[str, int] = {}
    for code in player.bonus_uses.values_list("code", flat=True):
        used[code] = used.get(code, 0) + 1
    return [
        {
            "label": spec.label,
            "scope": "weekend" if spec.scope is Scope.WEEKEND else "konkurs",
            "used": used.get(spec.code, 0),
            "limit": spec.season_limit,
            "available": used.get(spec.code, 0) < spec.season_limit,
        }
        for spec in SPECS.values()
    ]


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
