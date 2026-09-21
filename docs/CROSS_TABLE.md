# Kontrole między tabelami

Otwórz **Biblioteka reguł → Kontrole między tabelami**. Kreator generuje reguły typu `cross_table`, które działają lokalnie oraz po publikacji w Databricks. Istniejące reguły nie wymagają zmian.

## Przykład: kraj i waluta produktu

1. Zaimportuj do aplikacji produkty oraz `workspace.dq_app.ref_countries`. Lokalna kopia słownika jest potrzebna do wyboru kolumn i walidacji reguły. Samo wklejenie danych w rozmowie nie importuje tabeli.
2. W zakładce **Słowniki referencyjne** wpisz:

   | Pole | Wartość |
   |---|---|
   | Nazwa słownika | `countries` |
   | Lokalna tabela słownika | zaimportowana tabela krajów |
   | Profil połączenia | zapisany profil do tego workspace |
   | Katalog źródłowy | `workspace` |
   | Schemat źródłowy | `dq_app` |
   | Tabela źródłowa | `ref_countries` |

   Kliknij **Zapisz słownik**. Mapowanie zdalne jest opcjonalne dla lokalnych testów; dla Databricks wypełnij wszystkie pola. Źródło i słownik muszą być w tym samym workspace.

3. W zakładce **Utwórz regułę między tabelami** ustaw:
   - Opis: `Kraj i waluta produktu muszą pasować do słownika`.
   - Tabela: lokalna tabela produktów.
   - Nazwa słownika: `countries`.
   - Klucz rekordu: `product_id` — klucz istniejący także w Databricks, nie lokalny automatyczny `id`.
   - Warunek: **Pasujący rekord musi istnieć**.
   - Pary kolumn: `country_code → country_code` i `currency → currency_code`. Dodaj każdą parę przyciskiem.
   - Kolumna aktywności: `active_flag`, jeśli mają być dopuszczane wyłącznie aktywne wpisy. Puste pole pomija ten filtr.
   - Brakujące wartości: **NULL oznacza błąd**.
   - Ważność: `high`.
   - Komunikat: `Nieprawidłowa para kraj–waluta`.
4. Kliknij **Podgląd SQL**, a następnie **Utwórz regułę**.

`PL + PLN` przechodzi, `PL + EUR` nie przechodzi, o ile słownik zawiera tylko prawidłowy wpis dla Polski. `FRA` nie przechodzi, gdy słownik zawiera `FR`. Utwórz osobną regułę z jedną parą `country_code → country_code`, jeśli chcesz odrębnie raportować nieistniejące kody.

## Sposób porównania

- Domyślne dopasowanie jest dokładne. Opcja ignorowania wielkości liter i spacji stosuje `UPPER(TRIM(...))` po obu stronach; służy do pól tekstowych. Zachowanie dla znaków spoza ASCII zależy od silnika SQL.
- **NULL oznacza błąd** odrzuca brak dowolnej porównywanej wartości. **Pomiń NULL (PASS)** zalicza taki rekord jako PASS. Pusty tekst nie jest NULL.
- **Pasujący rekord nie może istnieć** odwraca kontrolę istnienia, np. pozwala sprawdzać listę niedopuszczalnych wartości. Zasada dla NULL nadal obowiązuje niezależnie.
- Kilka par musi zgadzać się w jednym rekordzie słownika.
- `EXISTS` / `NOT EXISTS` nie mnoży wyników przez duplikaty słownika. Nie naprawia jednak słownika: błędna dopuszczona para nadal może zatwierdzić błędne dane. Słownik powinien mieć własne reguły DQ.

## Uruchomienie i Databricks

Lokalnie wybierz zwykłe **Run checks → Lokalnie**. Zapytanie czyta obie lokalne tabele w jednej transakcji odczytu. Brak słownika lub kolumn jest błędem wykonania; nie oznacza automatycznie błędnych danych i nie zamyka ticketa.

Dla chmury otwórz **Databricks sync**, wybierz nową regułę i zmapuj źródło na `workspace.dq_app.products`. Program przygotuje SQL z `{{source}}` i `{{ref:countries}}`. Kliknij **Save mapping → Prepare DQ tables → Compare definitions → Publish**.

**Przy pierwszym przejściu na tę wersję zaimportuj ponownie zaktualizowany `artifacts/DQ_daily_checks.py`.** Nowe reguły mają kontrakt v2; stary notebook nie obsługuje ich zależności. Przygotowanie tabel dodaje kolumnę `reference_versions` do `dq_runs`, bez usuwania istniejących wyników. Jeśli harmonogram jest przypięty do starego notebooka, zaktualizuj jego kod albo wskaż nowy notebook i zachowaj parametry zadania.

Ręczne wykonanie z aplikacji i notebook zapisują wersję Delta źródła oraz wersję Delta słownika. Zapytanie używa obu ustalonych wersji, a synchronizacja weryfikuje ich obecność. W raporcie widać np. `countries: v4`. Pobieranie wyników odbywa się tak samo jak dla innych reguł.

## Edycja i pliki Git

Zmiana globalnego mapowania słownika wpływa na kolejne lokalne wykonania. Dla chmury trzeba ponownie porównać i opublikować każdą zależną regułę; opublikowane reguły zachowują poprzednie mapowanie do czasu publikacji. Stare wyniki zawierają dotychczasowe definicje i wersje Delta.

Kreator obsługuje jeden nazwany słownik na regułę i do 12 par kolumn. SQL jest generowany z konfiguracji; dowolne JOIN i ręczne modyfikowanie zapytania cross-table nie są obsługiwane w tej wersji. Aby zmienić pary, utwórz nową regułę i wyłącz poprzednią; zmiany metadanych pozostają dostępne w zwykłym edytorze.

Eksport reguł do Git zapisuje także konfigurację par (format v2). Import w innym środowisku wymaga wcześniejszego zarejestrowania tego samego aliasu słownika i lokalnych tabel. Profile, poświadczenia i rekordy danych nie są eksportowane.
