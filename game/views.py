from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from . import services
from .models import Player


@login_required
def home(request):
    standings = services.season_standings()
    players = {p.id: p for p in Player.objects.all()}
    rows = sorted(
        ((players[pid], pts) for pid, pts in standings.items() if pid in players),
        key=lambda row: (-row[1], row[0].order),
    )
    return render(request, "game/home.html", {"rows": rows})
