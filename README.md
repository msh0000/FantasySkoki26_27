# Fantasy Skoki 26/27

Aplikacja Django (Python) do zarządzania grą fantasy dla grupy znajomych.

## Uruchomienie lokalnie
```bash
uv sync
cp .env.example .env          # ustaw DJANGO_DEBUG=1
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```
Konta graczy zakładasz w panelu `/admin/`.

## Codzienna praca
```bash
uv run pytest        # testy
uv run ruff check .  # lint
uv run ruff format . # formatowanie
```

## Struktura
- `config/` - ustawienia projektu
- `game/rules.py` - logika zasad gry (czyste funkcje, łatwe do testowania)
- `game/models.py`, `game/views.py` - dane i widoki
- `templates/` - szablony HTML (Pico.css + HTMX)

## Zmiana zasad w trakcie sezonu
Zmieniamy `game/rules.py`, dopisujemy test, a zmiany w modelach robimy przez
`uv run python manage.py makemigrations` i `uv run python manage.py migrate`.
