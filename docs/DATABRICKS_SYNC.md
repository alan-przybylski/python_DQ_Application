# Synchronizacja reguł i wyników z Databricks

Aplikacja publikuje definicje reguł do tabeli `dq_rules` w Databricks. Notebook wykonuje je na danych Delta, a aplikacja pobiera wyniki i aktualizuje tickety. Komputer nie musi być włączony podczas wykonania zadania w chmurze.

## Pierwsza konfiguracja

1. Uruchom aplikację i zaloguj się jako superuser. Otwórz **Databricks sync** z dashboardu. Wybierz zapisany profil połączenia oraz lokalną regułę.
2. Ustaw osobny katalog/schemat na konfigurację i wyniki, np. `workspace.dq_control`. Wskaż źródłową tabelę Delta, np. `workspace.dq_app.products`.
3. W edytorze Spark SQL używaj `{{source}}` zamiast nazwy tabeli. Zwracaj kolejno trwały klucz źródłowy `AS id`, sprawdzane pole oraz całkowitoliczbowe `dq_check`: **0 = PASS, 1 = FAIL**. Lokalny automatycznie nadany `id` nie jest kluczem źródłowym; dla produktów użyj `product_id AS id`.

```sql
SELECT product_id AS id, sku,
       CASE WHEN COUNT(*) OVER (PARTITION BY sku) > 1
            THEN 1 ELSE 0 END AS dq_check
FROM {{source}}
```

4. Kliknij **Save mapping**, a następnie **Prepare DQ tables**. Ta druga operacja tworzy schemat i cztery tabele Delta; wymaga odpowiednich uprawnień w Databricks. Logowanie odbywa się przez OAuth w przeglądarce.
5. Kliknij **Compare definitions**, przejrzyj różnice i opublikuj regułę. Powtórz dla pozostałych reguł. Publikacja przełącza regułę na wykonanie w Databricks; lokalny silnik ją pomija.
6. Opcja **Download results after sign-in** włącza pobranie wyników po zalogowaniu do aplikacji. Ręcznie można użyć **Download results**. Pobranie wyników nie uruchamia notebooka i nie pobiera całego źródłowego zbioru danych.

## Notebook i codzienny harmonogram

### Przyciski w aplikacji

- **Download all results / Pobierz wszystkie wyniki** pobiera historię wszystkich mapowanych reguł Databricks, niezależnie od pozycji wybranej w edytorze. Nie trzeba wybierać reguł pojedynczo. Ponowne pobranie nie duplikuje wyników.
- **Run selected in Databricks / Uruchom wybraną w Databricks** wykonuje wybraną aktywną, opublikowaną regułę.
- **Run all in Databricks / Uruchom wszystkie w Databricks** wykonuje wszystkie aktywne, opublikowane reguły z lokalnych mapowań, także z różnych profili.

Ręczne wykonanie używa SQL warehouse z profilu i zapisanej wersji źródła Delta. Nie wymaga włączania notebooka ani zmiany harmonogramu. Wyniki zapisują się w tabelach kontrolnych w chmurze i od razu w lokalnych raportach oraz ticketach. Wykonywana jest **opublikowana definicja**, nie niezapisany szkic z edytora. Nieznaną zdalną wersję trzeba najpierw zaakceptować przez porównanie definicji. Wyłączenie reguły lokalnie lub w opublikowanej definicji wyklucza ją z ręcznego wykonania.

W tej wersji ręczne wykonanie pobiera ocenione rekordy do procesu aplikacji, z limitem 100 000 rekordów i 50 MB na regułę. Większe zbiory uruchamiaj notebookiem. Komputer i aplikacja muszą pozostać uruchomione podczas ręcznego testu; zamknięcie okna zatrzymuje kolejne reguły, ale rozpoczęta reguła może dokończyć się w tle. Codzienny notebook pozostaje niezależny od aplikacji.

Gotowy samodzielny notebook znajduje się w `artifacts/DQ_daily_checks.py`. Można go odtworzyć poleceniem `python -m scripts.build_databricks_notebook`. Nie zawiera poświadczeń ani lokalnych danych.

1. W Databricks Workspace wybierz Import i wgraj plik `DQ_daily_checks.py` jako notebook Python.
2. Wybierz dostępne środowisko serverless. Ustaw parametry `control_catalog=workspace`, `control_schema=dq_control`, **`setup_only=false`**. Domyślne `true` tylko przygotowuje tabele.
3. Uruchom **Run all**. Sprawdź wpisy w `workspace.dq_control.dq_runs`, a następnie pobierz wyniki w aplikacji.
4. Użyj **Schedule** w notebooku, utwórz zadanie codzienne, wybierz godzinę i strefę `Europe/Warsaw`. Sprawdź, że parametry zadania również mają `setup_only=false`. Konto wykonujące zadanie musi móc czytać źródło i zapisywać w schemacie kontrolnym.

Alternatywnie można użyć repozytorium jako Git folder i notebooka `databricks_dq_job.py` z pakietem `integrations` obok. Aktualizowanie kodu notebooka w Git i publikowanie definicji reguł to osobne operacje.

Dokumentacja: [harmonogram notebooka](https://docs.databricks.com/aws/en/notebooks/schedule-notebook-jobs), [ustawienia harmonogramu](https://docs.databricks.com/aws/en/jobs/scheduled). Dostępność wykonania w Free Edition zależy od limitów środowiska; samo zapisanie harmonogramu nie gwarantuje wykonania po wyczerpaniu limitu.

## Co zapisują tabele

| Tabela | Zawartość |
| --- | --- |
| `dq_rules` | Aktualne opublikowane definicje, identyfikatory i skróty wersji. |
| `dq_runs` | Jeden przebieg jednej reguły: czas, status techniczny, wersja reguły i wersja źródłowej tabeli Delta. |
| `dq_results` | Podsumowanie przebiegu: liczba PASS i FAIL oraz sprawdzane pole. |
| `dq_errors` | Konkretne błędne rekordy: klucz źródłowy, pole, wartość i opis błędu. |

Trzy tabele wykonania łączy `run_id`. Przykład: reguła SKU sprawdziła 1000 produktów, 995 PASS i 5 FAIL — jeden wpis w `dq_runs`, jeden w `dq_results`, pięć w `dq_errors`. Dla trzech reguł dzienne zadanie tworzy trzy przebiegi.

Status `completed` oznacza poprawne wykonanie SQL, również gdy są błędne dane. Status `failed` oznacza błąd wykonania. Aplikacja tworzy/aktualizuje ticket dla wykrytych błędów. Priorytet pochodzi z wykonanej wersji reguły, termin liczony jest od wykrycia w chmurze: low 7 dni, medium 3, high 1. Właścicielem jest użytkownik zapisujący mapowanie. Techniczna awaria ani pusty wynik nie zamykają ticketa.

## Zmiany i ograniczenia pierwszej wersji

- Publikacja jest jawna. Edycja, także dezaktywacja reguły lokalnie, wymaga ponownej publikacji. Zmianę z Databricks można pobrać przez porównanie definicji dla istniejącego mapowania; aplikacja nie odkrywa automatycznie nowych obcych reguł.
- Konflikt zdalnej wersji blokuje nadpisanie. Wersje użyte w wynikach są sprawdzane; nieznaną wersję trzeba najpierw zaakceptować przez porównanie definicji.
- Edytor zawiera Spark SQL. Sugestia na podstawie lokalnego SQL wymaga przejrzenia; nie jest to uniwersalny konwerter dialektów SQL.
- Zwykłe reguły obsługują pojedynczy SELECT z jednym `FROM {{source}}`, bez JOIN, UNION, CTE i podzapytań odczytujących inne tabele. Kontrole słownikowe tworzy dedykowany [kreator cross-table](CROSS_TABLE.md), z osobnym kontraktem i kontrolą zależności. Źródła i słowniki w chmurze muszą być tabelami Delta, nie widokami. Każda reguła czyta zapisane wersje Delta; różne reguły mogą odczytać różne wersje, jeśli dane zmienią się w trakcie zadania.
- Notebook materializuje ocenione rekordy w tymczasowej tabeli `dq_stage_<uuid>` w schemacie kontrolnym i usuwa ją na końcu. Przerwanie zadania może pozostawić taką tabelę do ręcznego usunięcia.
- Import jest odporny na ponowne pobranie tego samego przebiegu. Starszy przebieg uzupełnia historię, ale nie cofa aktualnego stanu ticketa.
- Pobieranie ma limity ochronne: 10 000 przebiegów na regułę, 100 000 szczegółów błędów i 50 MB na odczyt. Przekroczenie zgłasza błąd zamiast cichego ucięcia; większe wdrożenia wymagają stronicowania/retencji.
- Integracja wymaga pierwszego testu w docelowym workspace. Testy lokalne nie zastępują wykonania notebooka w Spark ani sprawdzenia uprawnień konta Databricks.
