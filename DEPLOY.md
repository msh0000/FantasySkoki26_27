# Deploy na PythonAnywhere (msh0000)

## Aktualizacja serwera (kod + dane + przeładowanie)
W konsoli Bash na PythonAnywhere jedna komenda:
```bash
bash ~/FantasySkoki26_27/update.sh
```
Skrypt robi `git pull`, instaluje zależności, wykonuje migracje i `collectstatic`, wczytuje
dane ze skijumping.pl (`load_snapshot`) i przeładowuje aplikację. Można go uruchamiać
wielokrotnie.

## Dane ze skijumping.pl (kalendarz, skoczkowie, wyniki)
Darmowy PythonAnywhere nie ma dostępu do skijumping.pl (ale ma do GitHuba) i nie ma
zaplanowanych zadań (są tylko w płatnych kontach), więc:

1. **GitHub Actions** (`.github/workflows/fetch-results.yml`) co godzinę pobiera dane i zapisuje je
   jako pliki JSON w `data/skijumping/` (commit "Dane ze skijumping.pl (automat)").
   Można je też odpalić ręcznie: GitHub -> zakładka **Actions** -> "Pobierz dane..." -> **Run workflow**.
2. **Serwer** wczytuje te pliki do bazy dopiero po uruchomieniu `update.sh` (ręcznie).
   Po konkursie: poczekaj, aż GitHub pobierze wyniki (albo odpal workflow ręcznie), potem
   uruchom `update.sh`.

### Lokalnie
`uv run python manage.py fetch_snapshot` pobiera dane do `data/skijumping/` (bez bazy),
a `load_snapshot` wczytuje je do lokalnej bazy. Starsze komendy `import_calendar`,
`import_jumpers` i `import_results ID` łączą się ze skijumping.pl bezpośrednio, więc działają
tylko tam, gdzie jest dostęp do tej strony (lokalnie, nie na darmowym PythonAnywhere).

## Co 3 miesiące
Na darmowym koncie w zakładce **Web** kliknij **Run until 3 months from today**.
