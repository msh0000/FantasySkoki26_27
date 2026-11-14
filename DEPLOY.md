# Deploy na PythonAnywhere (msh0000)

## Aktualizacja po zmianach w kodzie
W konsoli Bash na PythonAnywhere:
```bash
cd ~/FantasySkoki26_27 && git pull
source ~/.virtualenvs/fantasy/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
```
Potem zakładka **Web** -> **Reload**.
