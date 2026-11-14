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

## Ustalenia z drugiej rundy
- Każdy bonus raz na sezon (Typer: 3 razy, tylko konkursy mężczyzn, punkty wliczają się do weekendu).
- Gracz może mieć odpalony tylko 1 bonus na weekend (bonusy weekendowe) i 1 na konkurs (konkursowe).
- Zawodnik może być objęty tylko jednym bonusem w konkursie (kapitan, wiatr, czarna lista, patriota).
- Czarną Listę można użyć też na siebie, Podwójnego kapitana na zawodnika z cudzej drużyny.
- Miejsca poza top 30 = 0 pkt. Połówki punktów zostają (bez zaokrąglania).
- Norweg: nie można go użyć, jeśli ktoś już użył bonusu na tym graczu.
- Drużyna marzeń: 5 M + 1 K, bez ograniczeń unikalności, nadpisuje skład tylko na ten konkurs.
- Tomasz Pilich: do użycia przed oknem transferowym, przenosi gracza na początek kolejki
  (kolejne użycia = kolejne miejsca). **Pominięte w szkicu, robimy na końcu.**
- Remis w rankingu kolejki: wyżej w bazie (mniejsza "pozycja w bazie") = wyżej w rankingu.
- Ranking do kolejki: punkty z całego sezonu, liczone po zakończeniu poprzedniego weekendu.
- Źródło wyników: skijumping.pl (scraping).

## Założenia szkicu - DO POTWIERDZENIA
Zaimplementowane w `game/scoring.py` i `game/bonuses.py`, łatwe do zmiany:
1. Bonusy na zawodnika (kapitan, wiatr, czarna lista) działają na zawodnika, czyli zmieniają punkty
   tego, kto ma go w składzie w danym konkursie (także gdy użył ich ktoś inny).
2. Wiatr pod narty: x1.5 punktów, a poza top 5 dodatkowo -10 (kara obok punktów x1.5).
3. Typer: trafiony zawodnik z top 5 = 3 pkt, trafiony na dokładnym miejscu = 8 pkt (nie 3+8).
4. Popsute przeliczniki: miejsce r = r punktów (M do 30. miejsca, K do 10.).
5. Norweg chroni przed Kradzieżą, Kośćmi i Popsutymi przelicznikami, ale nie przed Czarną Listą.
6. Kolejność weekendu: konkursy + kary za transfery + korekty, potem pojedynek (+-20),
   na końcu premia 10 pkt dla najlepszej drużyny (liczona razem z pojedynkiem).
7. Mistrzostwa świata punktowane jak Puchar Świata.
8. Transfer w tej samej płci (M za M, K za K).
9. Patriota: dodatkowy Polak (kod kraju POL) wraca do składu na ten konkurs albo x2, gdy już w nim jest.
