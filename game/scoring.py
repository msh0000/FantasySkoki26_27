"""Liczenie punktów konkursów i weekendów (czyste funkcje, bez Django).

Punkty zawsze liczymy od nowa z surowych danych (wyniki, składy, bonusy), nie zapisujemy
ich na stałe - dzięki temu zmiana zasady to poprawka kodu i przeliczenie.

Założenia szkicu (do potwierdzenia, patrz docs/ZASADY.md):
- Bonusy na zawodnika (kapitan, wiatr, czarna lista) działają na zawodnika, więc wpływają
  na punkty tego, kto go ma w składzie w danym konkursie.
- Kolejność: składy (marzeń, kradzież, patriota) -> modyfikatory zawodników -> typer.
- Wiatr pod narty: punkty x1.5, a poza top 5 dodatkowo -10.
- Typer: trafiony zawodnik w top 5 = 3 pkt, trafione dokładne miejsce = 8 pkt (łącznie).
- Weekend: suma konkursów + kary za transfery + korekty, potem pojedynek (+-20),
  na końcu premia 10 pkt dla najlepszej drużyny (remis: wszyscy najlepsi dostają).
"""

from collections.abc import Collection
from dataclasses import dataclass, field

from . import rules
from .bonuses import (
    BLACKLIST,
    DOUBLE_CAPTAIN,
    DREAM_TEAM,
    DUEL,
    PATRIOT,
    REVERSED,
    STEAL,
    TYPER,
    WIND,
    Bonus,
)

DUEL_STAKE = 20
WIND_MULTIPLIER = 1.5
WIND_PENALTY = -10
WIND_TOP = 5
TYPER_HIT = 3
TYPER_EXACT = 8


@dataclass(frozen=True)
class JumperInfo:
    gender: str
    country: str
    name: str = ""


@dataclass
class PlayerScore:
    total: float = 0.0
    lines: list[tuple[str, float]] = field(default_factory=list)

    def add(self, label: str, points: float) -> None:
        self.lines.append((label, points))
        self.total += points


@dataclass
class CompetitionInput:
    label: str
    series: str
    gender: str  # M, K albo X (mieszany)
    ranks: dict[int, int]  # id zawodnika -> miejsce w klasyfikacji swojej płci
    rosters: dict[int, list[int]]  # id gracza -> id zawodników (skład z momentu konkursu)
    bonuses: list[Bonus] = field(default_factory=list)  # bonusy konkursowe tego konkursu


def _name(jumpers: dict[int, JumperInfo], jumper_id: int) -> str:
    info = jumpers.get(jumper_id)
    return info.name if info and info.name else f"zawodnik {jumper_id}"


def score_competition(
    comp: CompetitionInput,
    jumpers: dict[int, JumperInfo],
    reversed_players: Collection[int] = (),
) -> dict[int, PlayerScore]:
    rosters = {p: list(js) for p, js in comp.rosters.items()}
    by_code = {}
    for b in comp.bonuses:
        by_code.setdefault(b.code, []).append(b)

    # 1) Zmiany składów na ten konkurs.
    for b in by_code.get(DREAM_TEAM, []):
        rosters[b.player_id] = list(b.picks)
    for b in by_code.get(STEAL, []):
        mine, theirs = rosters.get(b.player_id), rosters.get(b.target_player_id)
        if mine is None or theirs is None:
            continue
        if b.target_jumper_id in theirs and b.give_jumper_id in mine:
            theirs[theirs.index(b.target_jumper_id)] = b.give_jumper_id
            mine[mine.index(b.give_jumper_id)] = b.target_jumper_id
    patriot_double: set[tuple[int, int]] = set()
    for b in by_code.get(PATRIOT, []):
        roster = rosters.setdefault(b.player_id, [])
        if b.target_jumper_id is None:
            continue
        if b.target_jumper_id in roster:
            patriot_double.add((b.player_id, b.target_jumper_id))
        else:
            roster.append(b.target_jumper_id)

    # 2) Modyfikatory zawodnika (pierwszy wygrywa; walidacja i tak nie pozwala na dwa).
    mods: dict[int, str] = {}
    for code in (DOUBLE_CAPTAIN, WIND, BLACKLIST):
        for b in by_code.get(code, []):
            mods.setdefault(b.target_jumper_id, code)

    scores = {p: PlayerScore() for p in rosters}
    for player_id, roster in rosters.items():
        score = scores[player_id]
        for jid in roster:
            info = jumpers[jid]
            rank = comp.ranks.get(jid)
            if player_id in reversed_players:
                base = rules.reversed_points(info.gender, rank)
            else:
                base = rules.points_for_rank(info.gender, comp.series, rank)

            points: float = base
            tag = ""
            mod = mods.get(jid)
            if mod == BLACKLIST:
                points, tag = 0, " (czarna lista)"
            elif mod == DOUBLE_CAPTAIN:
                points, tag = base * 2, " (x2 kapitan)"
            elif mod == WIND:
                points, tag = base * WIND_MULTIPLIER, " (x1.5 wiatr)"
            if (player_id, jid) in patriot_double:
                points, tag = points * 2, tag + " (x2 patriota)"
            score.add(f"{_name(jumpers, jid)}{tag}", points)
            if mod == WIND and (rank is None or rank > WIND_TOP):
                score.add(f"{_name(jumpers, jid)}: poza top {WIND_TOP} (wiatr)", WIND_PENALTY)

    # 3) Typer (tylko konkursy mężczyzn).
    if comp.gender == rules.MALE:
        for b in by_code.get(TYPER, []):
            score = scores.setdefault(b.player_id, PlayerScore())
            for position, jid in enumerate(b.picks, start=1):
                rank = comp.ranks.get(jid)
                if rank is None or rank > 5:
                    continue
                exact = rank == position
                score.add(
                    f"Typer: {_name(jumpers, jid)}" + (" (dokładne miejsce)" if exact else ""),
                    TYPER_EXACT if exact else TYPER_HIT,
                )
    return scores


def score_weekend(
    *,
    competitions: list[CompetitionInput],
    jumpers: dict[int, JumperInfo],
    players: list[int],
    weekend_bonuses: list[Bonus] = (),
    transfer_counts: dict[int, int] | None = None,
    adjustments: dict[int, float] | None = None,
) -> dict[int, PlayerScore]:
    transfer_counts = transfer_counts or {}
    adjustments = adjustments or {}
    result = {p: PlayerScore() for p in players}
    reversed_players = {b.target_player_id for b in weekend_bonuses if b.code == REVERSED}

    for comp in competitions:
        for player_id, score in score_competition(comp, jumpers, reversed_players).items():
            target = result.setdefault(player_id, PlayerScore())
            for label, pts in score.lines:
                target.add(f"{comp.label}: {label}", pts)

    for player_id, score in result.items():
        fee = rules.transfer_fee(transfer_counts.get(player_id, 0))
        if fee:
            score.add("Kara za dodatkowe transfery", fee)
        if adjustments.get(player_id):
            score.add("Korekta admina", adjustments[player_id])

    # Pojedynki liczymy na wynikach sprzed pojedynków, więc kolejność nie ma znaczenia.
    before = {p: s.total for p, s in result.items()}
    for b in weekend_bonuses:
        if b.code != DUEL or b.target_player_id not in before:
            continue
        mine, theirs = before[b.player_id], before[b.target_player_id]
        if mine > theirs:
            result[b.player_id].add("Pojedynek wygrany", DUEL_STAKE)
        elif mine < theirs:
            result[b.player_id].add("Pojedynek przegrany", -DUEL_STAKE)

    if competitions and result:
        best = max(s.total for s in result.values())
        for score in result.values():
            if score.total == best:
                score.add("Premia za najlepszy wynik weekendu", rules.WEEKEND_WINNER_BONUS)
    return result
