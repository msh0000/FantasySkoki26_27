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


def competition_rosters(competition: Competition) -> dict[int, list[int]]:
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


def skip_turn(weekend: Weekend, player: Player) -> None:
    slot = weekend.queue.filter(player=player).first()
    if slot and slot.status == QueueSlot.PENDING:
        slot.status = QueueSlot.SKIPPED
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

    out_jumper.owner = None
    out_jumper.save(update_fields=["owner"])
    in_jumper.owner = player
    in_jumper.save(update_fields=["owner"])
    slot = weekend.queue.filter(player=player).first()
    if slot and slot.status == QueueSlot.PENDING:
        slot.status = QueueSlot.DONE
        slot.save(update_fields=["status"])
    return Transfer.objects.create(
        weekend=weekend, player=player, out_jumper=out_jumper, in_jumper=in_jumper, made_by=made_by
    )
