"""Logika gry (czyste funkcje, bez Django) - tu trafiają zasady.

Trzymamy ją osobno od widoków i modeli, żeby łatwo ją testować i zmieniać
w trakcie sezonu, gdy zasady się zmienią.
"""


def next_transfer_player(order: list[int], done: set[int], skipped: set[int]) -> int | None:
    """Zwraca id gracza, który jest teraz na ruchu w kolejce transferów.

    Gracz na miejscu N czeka, aż wszyscy powyżej wykonają transfer lub zostaną pominięci.
    To tylko przykład - dopasujemy do prawdziwych zasad.
    """
    for player_id in order:
        if player_id not in done and player_id not in skipped:
            return player_id
    return None
