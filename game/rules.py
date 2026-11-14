"""Podstawowe zasady gry (czyste funkcje, bez Django).

Wszystkie liczby z zasad są tutaj jako stałe, żeby zmiana reguły w trakcie sezonu
oznaczała poprawkę w jednym miejscu + test.
"""

MALE, FEMALE, MIXED = "M", "K", "X"  # płeć skoczka (M, K) i typ konkursu (M, K, X = mieszany)
WC, TCS, WCH = "WC", "TCS", "WCH"  # Puchar Świata, Turniej Czterech Skoczni, Mistrzostwa Świata

FREE_TRANSFERS_PER_WEEKEND = 1
EXTRA_TRANSFER_FEE = -5
WEEKEND_WINNER_BONUS = 10

MEN_TOP5 = {1: 50, 2: 40, 3: 35, 4: 29, 5: 27}
MEN_MAX_RANK = 30
WOMEN_MAX_RANK = 10


def points_for_rank(gender: str, series: str, rank: int | None) -> int:
    """Punkty za miejsce w konkursie. `rank` to miejsce w klasyfikacji swojej płci."""
    if rank is None or rank < 1:
        return 0
    if gender == FEMALE:
        # Kobiety (także TCS): 1 -> 20, każde kolejne -2, tylko top 10.
        return 22 - 2 * rank if rank <= WOMEN_MAX_RANK else 0
    if series == TCS:
        # TCS mężczyźni: 1 -> 50, każde kolejne -5, tylko top 10.
        return 55 - 5 * rank if rank <= 10 else 0
    if rank in MEN_TOP5:
        return MEN_TOP5[rank]
    # Od 6. miejsca 25 pkt i -1 za miejsce, do 30. miejsca (1 pkt).
    return 31 - rank if rank <= MEN_MAX_RANK else 0


def reversed_points(gender: str, rank: int | None) -> int:
    """Bonus "Popsute przeliczniki": miejsce 1 -> 1 pkt, ..., miejsce 30 -> 30 pkt.

    Założenie (do potwierdzenia): u kobiet działa tylko dla miejsc 1-10.
    """
    if rank is None or rank < 1:
        return 0
    limit = WOMEN_MAX_RANK if gender == FEMALE else MEN_MAX_RANK
    return rank if rank <= limit else 0


def transfer_fee(transfers_in_weekend: int) -> int:
    """Kara punktowa (ujemna liczba) za transfery w jednym weekendzie."""
    return EXTRA_TRANSFER_FEE * max(0, transfers_in_weekend - FREE_TRANSFERS_PER_WEEKEND)


def queue_order(standings: dict[int, float], tiebreak: dict[int, int] | None = None) -> list[int]:
    """Kolejność transferów: od ostatniego miejsca w rankingu do pierwszego.

    Remis punktowy: wyżej w bazie (mniejszy `tiebreak`) = wyżej w rankingu = później w kolejce.
    """
    tiebreak = tiebreak or {}
    return sorted(standings, key=lambda p: (standings[p], -tiebreak.get(p, 0)))


def can_act_in_queue(queue: list[int], resolved: set[int], player_id: int) -> bool:
    """Czy gracz może teraz zrobić transfer.

    `resolved` to gracze, którzy już zrobili transfer lub go pominęli. Gdy kolejka przejdzie
    przez wszystkich, każdy może działać bez kolejki ("kto pierwszy").
    """
    if player_id not in queue or all(p in resolved for p in queue):
        return True
    if player_id in resolved:
        return False
    position = queue.index(player_id)
    return all(p in resolved for p in queue[:position])


def players_to_confirm_skip(queue: list[int], resolved: set[int], player_id: int) -> list[int]:
    """Gracze przed `player_id`, którzy jeszcze nie ruszyli (do potwierdzenia pominięcia)."""
    if player_id not in queue:
        return []
    return [p for p in queue[: queue.index(player_id)] if p not in resolved]
