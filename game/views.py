from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import rules, services
from .forms import DraftForm
from .models import Jumper, Player, QueueSlot, Weekend


def _current_player(request) -> Player | None:
    return Player.objects.filter(user=request.user).first()


@login_required
def home(request):
    standings = services.season_standings()
    players = {p.id: p for p in Player.objects.all()}
    rows = sorted(
        ((players[pid], pts) for pid, pts in standings.items() if pid in players),
        key=lambda row: (-row[1], row[0].order),
    )
    return render(request, "game/home.html", {"rows": rows, "me": _current_player(request)})


@login_required
def team(request, player_id=None):
    me = _current_player(request)
    player = get_object_or_404(Player, pk=player_id) if player_id else me
    if player is None:
        return render(request, "game/no_player.html")
    jumpers = player.jumpers.all()
    return render(
        request,
        "game/team.html",
        {
            "player": player,
            "is_me": me is not None and me.pk == player.pk,
            "men": jumpers.filter(gender="M"),
            "women": jumpers.filter(gender="K"),
            "bonuses": services.bonus_overview(player),
            "players": Player.objects.all(),
        },
    )


@login_required
def weekends(request):
    now = timezone.now()
    items = []
    for weekend in Weekend.objects.annotate(n_competitions=Count("competitions")):
        first = weekend.first_start()
        items.append(
            {
                "weekend": weekend,
                "first": first,
                "locked": first is not None and now >= first,
            }
        )
    upcoming = [i for i in items if not i["locked"]]
    past = [i for i in items if i["locked"]]
    return render(
        request,
        "game/weekends.html",
        {"upcoming": upcoming, "past": list(reversed(past))},
    )


@login_required
def weekend_detail(request, pk):
    weekend = get_object_or_404(Weekend, pk=pk)
    scores = services.weekend_scores(weekend)
    players = {p.id: p for p in Player.objects.all()}
    rows = sorted(
        ((players[pid], score) for pid, score in scores.items() if pid in players),
        key=lambda row: (-row[1].total, row[0].order),
    )
    competitions = weekend.competitions.annotate(n_results=Count("results"))
    return render(
        request,
        "game/weekend_detail.html",
        {
            "weekend": weekend,
            "rows": rows,
            "competitions": competitions,
            "locked": weekend.is_locked(),
            "me": _current_player(request),
        },
    )


@login_required
def draft(request):
    """Ręczne przypisanie składów po drafcie (tylko dla admina)."""
    if not request.user.is_staff:
        raise PermissionDenied
    players = list(Player.objects.all())
    forms = [DraftForm(p, request.POST or None, prefix=str(p.pk)) for p in players]
    if request.method == "POST" and not forms:
        messages.error(request, "Nie ma żadnych graczy - najpierw dodaj ich w panelu admina.")
    elif request.method == "POST":
        if all([form.is_valid() for form in forms]):
            selection = {form.player: form.chosen() for form in forms}
            conflicts = services.draft_conflicts(selection)
            if conflicts:
                for message in conflicts:
                    messages.error(request, message)
            else:
                services.assign_rosters(selection)
                messages.success(request, "Składy zapisane.")
                return redirect("draft")
    return render(request, "game/draft.html", {"forms": forms})


# --- Transfery ------------------------------------------------------------------------------


def _transfer_context(request, weekend: Weekend) -> dict:
    me = _current_player(request)
    slots = list(weekend.queue.select_related("player"))
    queue = [s.player_id for s in slots]
    resolved = {s.player_id for s in slots if s.status != QueueSlot.PENDING}
    status_by_player = {s.player_id: s.status for s in slots}
    counts = services.transfers_made(weekend)
    free = Jumper.objects.filter(active=True, owner__isnull=True).order_by("gender", "name")
    cards = []
    for player in Player.objects.all():
        waiting_for = rules.players_to_confirm_skip(queue, resolved, player.pk)
        names = {p.pk: p.name for p in Player.objects.filter(pk__in=waiting_for)}
        cards.append(
            {
                "player": player,
                "is_me": me is not None and me.pk == player.pk,
                "jumpers": list(player.jumpers.all()),
                "status": status_by_player.get(player.pk),
                "status_label": dict(QueueSlot.STATUSES).get(status_by_player.get(player.pk), ""),
                "can_act": rules.can_act_in_queue(queue, resolved, player.pk) if slots else False,
                "waiting_for": [names[i] for i in waiting_for],
                "is_turn": bool(slots)
                and status_by_player.get(player.pk) == QueueSlot.PENDING
                and not waiting_for,
                "made": counts.get(player.pk, 0),
                "next_fee": rules.transfer_fee(counts.get(player.pk, 0) + 1),
            }
        )
    return {
        "weekend": weekend,
        "weekends": Weekend.objects.all(),
        "locked": weekend.is_locked(),
        "has_queue": bool(slots),
        "slots": slots,
        "cards": cards,
        "free_men": free.filter(gender="M"),
        "free_women": free.filter(gender="K"),
        "history": weekend.transfers.select_related("player", "out_jumper", "in_jumper").order_by(
            "-created_at"
        ),
        "me": me,
    }


@login_required
def transfers(request, weekend_id=None):
    weekend = (
        get_object_or_404(Weekend, pk=weekend_id)
        if weekend_id
        else services.current_transfer_weekend()
    )
    if weekend is None:
        return render(request, "game/transfers.html", {"weekend": None})
    return render(request, "game/transfers.html", _transfer_context(request, weekend))


def _override(request) -> bool:
    """Tryb admina: pomija kolejkę i blokadę weekendu (tylko dla staff)."""
    return request.user.is_staff and request.POST.get("override") == "1"


@login_required
@require_POST
def transfer_open(request, weekend_id):
    if not request.user.is_staff:
        raise PermissionDenied
    weekend = get_object_or_404(Weekend, pk=weekend_id)
    if weekend.queue.exists():
        messages.info(request, "Okno transferowe jest już otwarte.")
    else:
        services.build_queue(weekend)
        messages.success(request, "Okno transferowe otwarte - kolejka utworzona wg rankingu.")
    return redirect("transfers_for", weekend_id=weekend.pk)


@login_required
@require_POST
def transfer_make(request, weekend_id):
    """Transfer w turze gracza (dowolnie wiele). Tury nie kończy - robi to transfer_pass."""
    weekend = get_object_or_404(Weekend, pk=weekend_id)
    player = get_object_or_404(Player, pk=request.POST.get("player"))
    override = _override(request)
    if not weekend.queue.exists() and not override:
        messages.error(request, "Okno transferowe nie zostało jeszcze otwarte.")
        return redirect("transfers_for", weekend_id=weekend.pk)
    out_jumper = Jumper.objects.filter(pk=request.POST.get("out") or None).first()
    in_jumper = Jumper.objects.filter(pk=request.POST.get("in") or None).first()
    if out_jumper is None or in_jumper is None:
        messages.error(request, "Wybierz zawodnika do oddania i zawodnika do wzięcia.")
        return redirect("transfers_for", weekend_id=weekend.pk)
    try:
        services.make_transfer(
            weekend,
            player,
            out_jumper,
            in_jumper,
            made_by=request.user,
            enforce_queue=not override,
            enforce_lock=not override,
        )
    except services.TransferError as error:
        messages.error(request, str(error))
    else:
        fee = rules.transfer_fee(services.transfers_made(weekend).get(player.pk, 0))
        suffix = f" Kara: {fee} pkt." if fee else ""
        messages.success(request, f"{player.name}: {out_jumper.name} → {in_jumper.name}.{suffix}")
    return redirect("transfers_for", weekend_id=weekend.pk)


@login_required
@require_POST
def transfer_confirm(request, weekend_id):
    """Potwierdzenie, że gracze przed nami w kolejce pominęli swoje transfery."""
    weekend = get_object_or_404(Weekend, pk=weekend_id)
    player = get_object_or_404(Player, pk=request.POST.get("player"))
    if weekend.is_locked() and not _override(request):
        messages.error(request, "Weekend już się rozpoczął.")
        return redirect("transfers_for", weekend_id=weekend.pk)
    waiting = services.players_to_confirm_skip(weekend, player)
    if not waiting:
        messages.info(request, "Nikt przed Tobą nie czeka - to już Twoja kolej.")
    else:
        for skipped in waiting:
            services.finish_turn(weekend, skipped)
        names = ", ".join(p.name for p in waiting)
        messages.success(request, f"Pominięci: {names}. Teraz kolej: {player.name}.")
    return redirect("transfers_for", weekend_id=weekend.pk)


@login_required
@require_POST
def transfer_pass(request, weekend_id):
    """Koniec tury gracza: oddaje pałeczkę następnemu w kolejce."""
    weekend = get_object_or_404(Weekend, pk=weekend_id)
    player = get_object_or_404(Player, pk=request.POST.get("player"))
    override = _override(request)
    if weekend.is_locked() and not override:
        messages.error(request, "Weekend już się rozpoczął.")
    elif not override and services.players_to_confirm_skip(weekend, player):
        messages.error(request, "Najpierw potwierdź pominięcie graczy przed Tobą w kolejce.")
    else:
        services.finish_turn(weekend, player)
        messages.success(request, f"{player.name} kończy swoją kolejkę.")
    return redirect("transfers_for", weekend_id=weekend.pk)
