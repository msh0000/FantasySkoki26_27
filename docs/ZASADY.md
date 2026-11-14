# Zasady gry Fantasy Skoki 26/27

Dokument roboczy: spisane zasady (stan z rozmowy). Kod w `game/rules.py` ma je odzwierciedlać.
Rzeczy oznaczone **[DO USTALENIA]** nie są jeszcze rozstrzygnięte.

## Skład
- 7 graczy. Każdy ma 5 skoczków (M) i 1 skoczkinię (K).
- Zawodnik może należeć tylko do jednego gracza. Brak kapitanów, rezerwowych, budżetu i limitów krajów.
- Draft odbywa się poza aplikacją (Discord), składy wprowadza admin.
- Pula: ok. 201 skoczków, lista będzie się powiększać.

## Punkty za konkurs (miejsce indywidualne, remisy = takie same punkty)
- **Mężczyźni (PŚ):** 1:50, 2:40, 3:35, 4:29, 5:27, 6:25, 7:24 ... 30:1 (od 6. miejsca -1 za miejsce).
- **Kobiety (PŚ):** 1:20, 2:18 ... 10:2 (tylko top 10, co 2).
- **TCS mężczyźni:** 1:50, 2:45 ... 10:5 (top 10, co 5).
- **TCS kobiety:** jak zwykły konkurs kobiet.
- Liczą się: Puchar Świata, TCS, mistrzostwa świata. Nie liczą się igrzyska ani Raw Air.
- Kalendarze kobiet i mężczyzn się różnią.
- Konkursy mieszane: skoczek dostaje punkty za ranking indywidualny, a ranking K i M jest osobny. **[DO USTALENIA technicznie: skąd brać ranking indywidualny w drużynówce]**

## Weekend
- Premia 10 pkt dla drużyny z największą liczbą punktów w weekendzie (remis: każda dostaje 10).
- Do wyniku weekendu wliczamy bonusy i kary za transfery.

## Transfery
- Zamiana 1 za 1 z wolnym zawodnikiem z puli. 1 darmowy na weekend, każdy kolejny -5 pkt. Niewykorzystane nie przechodzą dalej.
- Kolejka: od ostatniego miejsca w rankingu sezonowym do pierwszego. Ranking liczony po zakończeniu poprzedniego weekendu.
- Gracz na miejscu N czeka, aż gracze poniżej zrobią transfer lub go pominą.
- Pominięcie: gracz potwierdza, że pozostali, którzy jeszcze nie zrobili ruchu, zgodzili się pominąć (na uczciwość).
- Gdy kolejka przejdzie przez wszystkich (miejsce 1 zrobiło transfer lub pominęło), każdy może robić transfery bez kolejki ("kto pierwszy").
- Gracze mogą robić transfery i odpalać bonusy w imieniu innych (po uzgodnieniu na Messengerze).
- Admin może edytować wszystko także w trakcie weekendu.
- Blokada transferów i bonusów: start pierwszej serii (weekendowe: pierwszego konkursu weekendu, konkursowe: danego konkursu).

## Bonusy (11)
Typ "Konkurs" = raz na konkurs, "Weekend" = raz na weekend. Użycie przed rozpoczęciem.

| # | Nazwa | Typ | Efekt |
|---|-------|-----|-------|
| 1 | Podwójny kapitan | Konkurs | Punkty wybranego zawodnika x2 |
| 2 | Kradzież | Konkurs | Wymiana z wybranym graczem na jeden konkurs: bierzesz jego dowolnego zawodnika, dajesz mu swojego |
| 3 | Kości zostały rzucone | Weekend | Pojedynek z wybranym graczem: więcej punktów na koniec weekendu = +20, mniej = -20. Przeciwnik bez zmian. Liczony jako ostatni |
| 4 | Typer | Konkurs | Typujesz top 5: trafiony zawodnik +3, trafione dokładne miejsce +8. Do wykorzystania 3 razy |
| 5 | Drużyna marzeń | Konkurs | Wybierasz dowolną drużynę na konkurs, punkty aktualnej się nie liczą. Zasada unikalności nie obowiązuje |
| 6 | Wiatr pod narty | Konkurs | Punkty wybranego zawodnika x1.5, ale poza top 5 = -10 |
| 7 | Tomasz Pilich | Weekend | Transfer bez kolejki |
| 8 | Czarna Lista | Konkurs | Wybrany zawodnik dostaje 0 pkt |
| 9 | Popsute przeliczniki | Weekend | Punkty wybranego gracza liczone na odwrót: miejsce 1 = 1 pkt, miejsce 30 = 30 pkt |
| 10 | Patriota | Konkurs | Dodatkowy Polak na jeden konkurs; jeśli już jest w składzie, jego punkty x2 |
| 11 | Norweg | Weekend | Nikt nie może użyć na tobie żadnego bonusu |

## Dane o wynikach
Wyniki mają być pobierane automatycznie (scraping lub API), nie ręcznie.
