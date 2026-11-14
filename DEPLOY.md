# Deploy na PythonAnywhere (msh0000)

## Aktualizacja po zmianach w kodzie
W konsoli Bash na PythonAnywhere:
```bash
cd ~/FantasySkoki26_27 && git pull
source ~/.virtualenvs/fantasy/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py load_snapshot
```
Potem zakładka **Web** -> **Reload**.

## Dane ze skijumping.pl (kalendarz, skoczkowie, wyniki)
Darmowy PythonAnywhere nie ma dostępu do skijumping.pl (ale ma do GitHuba), więc:

1. **GitHub Actions** (`.github/workflows/fetch-results.yml`) co godzinę pobiera dane i zapisuje je
   jako pliki JSON w `data/skijumping/` (commit "Dane ze skijumping.pl (automat)").
   Można je też odpalić ręcznie: GitHub -> zakładka **Actions** -> "Pobierz dane..." -> **Run workflow**.
2. **Serwer** robi `git pull` i `python manage.py load_snapshot`, które wczytuje pliki do bazy.
   Polecenie można uruchamiać wielokrotnie (nic nie dubluje).

### Automatyczne wczytywanie na serwerze (zakładka Tasks)
PythonAnywhere -> **Tasks** -> **Scheduled** -> dodaj zadanie dzienne (darmowy plan pozwala na jedno):
```bash
cd ~/FantasySkoki26_27 && git pull -q && ~/.virtualenvs/fantasy/bin/python manage.py load_snapshot
```
Po konkursie, gdy chcesz mieć wyniki od razu, uruchom tę samą linię ręcznie w konsoli Bash
(po tym, jak GitHub Actions pobierze wyniki).

### Lokalnie
`uv run python manage.py fetch_snapshot` pobiera dane do `data/skijumping/` (bez bazy),
a `load_snapshot` wczytuje je do lokalnej bazy. Starsze komendy `import_calendar`,
`import_jumpers` i `import_results ID` łączą się ze skijumping.pl bezpośrednio, więc działają
tylko tam, gdzie jest dostęp do tej strony (lokalnie, nie na darmowym PythonAnywhere).
