"""Definicje 11 bonusów i walidacja ich użycia (czyste funkcje, bez Django)."""

from dataclasses import dataclass
from enum import StrEnum


class Scope(StrEnum):
    WEEKEND = "weekend"
    COMPETITION = "competition"


DOUBLE_CAPTAIN = "double_captain"
STEAL = "steal"
DUEL = "duel"
TYPER = "typer"
DREAM_TEAM = "dream_team"
WIND = "wind"
PILICH = "pilich"
BLACKLIST = "blacklist"
REVERSED = "reversed"
PATRIOT = "patriot"
NORWAY = "norway"


@dataclass(frozen=True)
class BonusSpec:
    code: str
    label: str
    scope: Scope
    season_limit: int = 1


SPECS: dict[str, BonusSpec] = {
    s.code: s
    for s in [
        BonusSpec(DOUBLE_CAPTAIN, "Podwójny kapitan", Scope.COMPETITION),
        BonusSpec(STEAL, "Kradzież", Scope.COMPETITION),
        BonusSpec(DUEL, "Kości zostały rzucone", Scope.WEEKEND),
        BonusSpec(TYPER, "Typer", Scope.COMPETITION, season_limit=3),
        BonusSpec(DREAM_TEAM, "Drużyna marzeń", Scope.COMPETITION),
        BonusSpec(WIND, "Wiatr pod narty", Scope.COMPETITION),
        BonusSpec(PILICH, "Tomasz Pilich", Scope.WEEKEND),
        BonusSpec(BLACKLIST, "Czarna Lista", Scope.COMPETITION),
        BonusSpec(REVERSED, "Popsute przeliczniki", Scope.WEEKEND),
        BonusSpec(PATRIOT, "Patriota", Scope.COMPETITION),
        BonusSpec(NORWAY, "Norweg", Scope.WEEKEND),
    ]
}
CHOICES = [(s.code, s.label) for s in SPECS.values()]

# Bonusy działające na konkretnego zawodnika - dany zawodnik może być "dotknięty" tylko jednym.
JUMPER_TARGETING = {DOUBLE_CAPTAIN, WIND, BLACKLIST, PATRIOT}
# Bonusy wymierzone w gracza - Norweg przed nimi chroni.
PLAYER_TARGETING = {STEAL, DUEL, REVERSED}


@dataclass(frozen=True)
class Bonus:
    code: str
    player_id: int
    weekend_id: int
    competition_id: int | None = None
    target_player_id: int | None = None
    target_jumper_id: int | None = None
    give_jumper_id: int | None = None
    picks: tuple[int, ...] = ()


def validate_bonus_use(new: Bonus, existing: list[Bonus]) -> list[str]:
    """Zwraca listę błędów (pusta = użycie jest poprawne). `existing` to inne użycia w sezonie."""
    spec = SPECS[new.code]
    errors: list[str] = []

    if spec.scope is Scope.COMPETITION and new.competition_id is None:
        errors.append("Ten bonus wymaga wskazania konkursu.")
    if spec.scope is Scope.WEEKEND and new.competition_id is not None:
        errors.append("Ten bonus dotyczy całego weekendu, nie pojedynczego konkursu.")

    if sum(1 for b in existing if b.player_id == new.player_id and b.code == new.code) >= (
        spec.season_limit
    ):
        errors.append(f"Limit użyć bonusu „{spec.label}” w sezonie został wykorzystany.")

    for b in existing:
        if b.player_id != new.player_id or SPECS[b.code].scope is not spec.scope:
            continue
        same_slot = (
            b.weekend_id == new.weekend_id
            if spec.scope is Scope.WEEKEND
            else b.competition_id == new.competition_id
        )
        if same_slot:
            errors.append("Gracz ma już odpalony bonus w tym weekendzie/konkursie.")
            break

    if new.code in JUMPER_TARGETING:
        if new.target_jumper_id is None:
            errors.append("Wskaż zawodnika.")
        elif any(
            b.code in JUMPER_TARGETING
            and b.competition_id == new.competition_id
            and b.target_jumper_id == new.target_jumper_id
            for b in existing
        ):
            errors.append("Ten zawodnik jest już objęty innym bonusem w tym konkursie.")

    if new.code in PLAYER_TARGETING:
        if new.target_player_id is None:
            errors.append("Wskaż gracza.")
        else:
            if new.code != REVERSED and new.target_player_id == new.player_id:
                errors.append("Tego bonusu nie można użyć na sobie.")
            if any(
                b.code == NORWAY
                and b.player_id == new.target_player_id
                and b.weekend_id == new.weekend_id
                for b in existing
            ):
                errors.append("Ten gracz ma Norwega - nie można użyć na nim bonusu.")

    if new.code == STEAL and (new.target_jumper_id is None or new.give_jumper_id is None):
        errors.append("Kradzież wymaga zawodnika, którego bierzesz, i tego, którego oddajesz.")

    if new.code == NORWAY and any(
        b.target_player_id == new.player_id
        and b.weekend_id == new.weekend_id
        and b.player_id != new.player_id
        for b in existing
    ):
        errors.append("Ktoś już użył bonusu na tym graczu - Norweg niedostępny.")

    if new.code == TYPER and len(set(new.picks)) != 5:
        errors.append("Typer wymaga 5 różnych zawodników.")
    if new.code == DREAM_TEAM and len(set(new.picks)) != 6:
        errors.append("Drużyna marzeń wymaga 6 różnych zawodników (5 M + 1 K).")

    return errors
