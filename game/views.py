from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from . import services
from .forms import DraftForm
from .models import Player, Weekend


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
    if request.method == "POST":
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
