# Tabele i reguły: lokalnie lub w Databricks

## Codzienna praca

1. Otwórz **SQL editor → Importuj tabele**. Zaimportuj plik lub tabelę z Databricks. Nazwij lokalną tabelę tak, jak ma się nazywać w Databricks. Import z Databricks podpowiada nazwę źródłową.
2. W edytorze pisz zwykły SQL, używając nazw widocznych po lewej stronie. Działają zapytania między tabelami, np. JOIN i EXISTS. Dla reguły zwróć kolejno `id`, sprawdzane pole i całkowitoliczbowe `dq_check`: **0 = PASS, 1 = FAIL**.
3. Kliknij **Create rule** i zapisz regułę dla sprawdzanej tabeli.
4. Jeśli chcesz pracować w chmurze, wybierz tabelę i **Wyślij tabelę do Databricks**. Powtórz dla pozostałych tabel użytych w SQL.
5. W bibliotece zaznacz regułę i wybierz **Wyślij regułę do Databricks**. Program sprawdzi wszystkie tabele i SQL oraz przygotuje przechowywanie wyników. Nie konfigurujesz osobnego mapowania dla każdej reguły.
6. W **Run checks** wybierz **Lokalnie** lub **Databricks**. Ręczne wykonanie w chmurze automatycznie pobiera wynik do raportu i ticketów. **Pobierz wszystkie wyniki** pobiera również wyniki niezależnych zadań.

## Nazwy i połączenie

Wybierasz zapisany profil połączenia. Jego katalog i schemat są wspólne dla wysyłanych tabel. Przykładowo `ref_countries` lokalnie trafia do `workspace.dq_app.ref_countries`. W SQL używasz krótkiej nazwy `ref_countries`; program dopisuje katalog i schemat.

Wysłanie istniejącej tabeli wymaga zaznaczenia **Zastąp istniejącą tabelę Databricks (kolumny i dane)** i potwierdzenia. Bez tej opcji istniejąca tabela nie jest nadpisywana. Upload najpierw zapisuje i sprawdza oddzielną tabelę roboczą, a następnie podmienia cel. Nieudany zapis danych nie podmienia celu. Dane źródłowe lokalnie pozostają bez zmian.

Program nie przenosi automatycznie istniejących tabel o historycznych nazwach ani starych reguł wskazujących inny cel. Dla nowego przepływu używaj docelowych nazw od importu. Stare opublikowane reguły, ich wyniki oraz tickety nadal działają.

## Codzienny harmonogram

Zaimportuj aktualny `artifacts/DQ_daily_checks.py` do Databricks. Plik można odtworzyć poleceniem `python -m scripts.build_databricks_notebook`. Notebook instaluje parser SQL, przygotowuje tabele wynikowe i wykonuje opublikowane reguły.

Ustaw `control_catalog` na katalog profilu, `control_schema=dq_control` i `setup_only=false`. Najpierw wykonaj **Run all**, a następnie skonfiguruj **Schedule** na wybraną godzinę i strefę `Europe/Warsaw`. Jeśli masz już zadanie, zaktualizuj notebook, do którego jest przypięte. Komputer nie musi działać podczas wykonania harmonogramu.

[Dokumentacja harmonogramów Databricks](https://docs.databricks.com/aws/en/notebooks/schedule-notebook-jobs).

## Wyniki i ograniczenia

- `dq_runs` zapisuje wykonanie jednej reguły i wersje Delta wszystkich użytych tabel; `dq_results` liczby PASS/FAIL; `dq_errors` błędne rekordy. Pobieranie nie duplikuje historii.
- Reguła pozostaje dostępna lokalnie po wysłaniu. Chmura wykonuje ostatnią opublikowaną wersję; po edycji wyślij ją ponownie. Wyłączenie reguły dla harmonogramu również wymaga wysłania zmiany.
- SQL jest tłumaczony z SQLite do Databricks i sprawdzany w chmurze przed publikacją. Nie każda funkcja SQL jest przenośna. W pierwszej wersji krótkie nazwy muszą należeć do jednego katalogu i schematu profilu; źródła chmurowe dla reguł muszą być tabelami Delta.
- Upload oraz ręczne wykonanie mają limit 100 000 rekordów / 50 MB. Notebook może przetwarzać większe źródła; pobieranie szczegółów błędów zachowuje swoje limity.
- Import zachowuje istniejący całkowitoliczbowy, unikalny `id`. Jeśli źródło nie ma `id`, lokalna kopia otrzymuje identyfikator techniczny. Wysyłanie tej kopii przenosi też ten identyfikator. Przy wykonaniu na oryginalnej tabeli chmurowej użyj w SQL istniejącego klucza źródła `AS id`; program nie zgaduje klucza ani nie zmienia nazw kolumn po cichu.
- Typy danych są konwertowane do wspólnego zakresu SQLite (INTEGER, REAL, TEXT). Precyzyjne typy źródłowe, np. DECIMAL lub TIMESTAMP, mogą być lokalnie przechowywane jako tekst. Upload wysyła schemat lokalny.
- Zamknięcie aplikacji może przerwać ręczny transfer/test. Zaplanowany notebook działa niezależnie. Testy lokalne nie zastępują pierwszego wykonania na Twoim koncie Databricks.
