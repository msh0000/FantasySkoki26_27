#!/bin/bash
# Aktualizacja aplikacji na serwerze (PythonAnywhere): kod, zależności, baza, dane, przeładowanie.
# Uruchamianie: bash ~/FantasySkoki26_27/update.sh
set -euo pipefail

cd "$(dirname "$0")"
source ~/.virtualenvs/fantasy/bin/activate

git pull
pip install -q -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput -v0
python manage.py load_snapshot
python manage.py import_jumper_list

# Przeładowanie aplikacji (to samo co przycisk Reload w zakładce Web).
WSGI=/var/www/msh0000_pythonanywhere_com_wsgi.py
if [ -f "$WSGI" ]; then
  touch "$WSGI"
  echo "Aplikacja przeładowana."
else
  echo "Nie znaleziono $WSGI - kliknij Reload w zakładce Web."
fi
