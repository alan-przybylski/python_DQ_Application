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

Istniejące jawne powiązania tabel są wykorzystywane również przy publikowaniu
nowych reguł. Na przykład lokalne `databricks_products` może nadal wskazywać
`workspace.dq_app.products`; aplikacja dopasuje nazwę przy publikacji. W edytorze
i w definicji reguły używaj lokalnej nazwy. Bez istniejącego powiązania obowiązuje
ta sama nazwa tabeli lokalnie i w chmurze.

### Jeden SQL w edytorze i w formularzu reguły

Nie musisz wpisywać `{{SOURCE}}`. Zwykłe `FROM databricks_products` działa w
edytorze i zapisanej regule. Opcjonalny znacznik `{{SOURCE}}` / `{{source}}`
oznacza tabelę zaznaczoną po lewej w edytorze albo wybraną w formularzu reguły.
Przy zapisie jest zastępowany rzeczywistą nazwą lokalną. Bez wyboru tabeli edytor
prosi o jej wybranie; tekst w komentarzach i literałach nie jest zmieniany.
Zakładka **Definition** pokazuje lokalny SQL, a nie historyczny szablon chmurowy.

Przykład dla lokalnej kopii produktów:

```sql
SELECT product_id AS id, launch_date,
       CASE WHEN launch_date IS NULL THEN 1 ELSE 0 END AS dq_check
FROM databricks_products;
```

Przy publikacji na oryginalnym źródle korzystaj z istniejącego w nim klucza
(`product_id AS id` w tym przykładzie). Dodatkowy lokalny techniczny `id` nie
pojawia się automatycznie w oryginalnej tabeli Databricks. Walidacja w chmurze
sprawdza kolumny przed publikacją; aplikacja nie podmienia kluczy po cichu.

## Codzienny harmonogram

Zaimportuj aktualny `artifacts/DQ_daily_checks.py` do Databricks. Plik można odtworzyć poleceniem `python -m scripts.build_databricks_notebook`. Notebook instaluje parser SQL, przygotowuje tabele wynikowe i wykonuje opublikowane reguły.

Ustaw `control_catalog` na katalog profilu, `control_schema=dq_control` i `setup_only=false`. Najpierw wykonaj **Run all**, a następnie skonfiguruj **Schedule** na wybraną godzinę i strefę `Europe/Warsaw`. Jeśli masz już zadanie, zaktualizuj notebook, do którego jest przypięte. Komputer nie musi działać podczas wykonania harmonogramu.

**Wpisz te trzy wartości także w parametrach zadania notebookowego w jobie.**
Wartość widoczna w widżecie otwartego notebooka nie jest potwierdzeniem parametrów
harmonogramu. Starszy notebook miał domyślne `setup_only=true`: job kończył się
sukcesem po przygotowaniu tabel, bez uruchomienia checków. Aktualny notebook
domyślnie wykonuje checki, wypisuje liczbę wykonań i zgłasza błąd, jeśli nie ma
aktywnych opublikowanych reguł. Tryb `setup_only=true` pozostaje dostępny do
samego przygotowania tabel i wypisuje ostrzeżenie o braku wykonanych checków.

[Dokumentacja harmonogramów Databricks](https://docs.databricks.com/aws/en/notebooks/schedule-notebook-jobs).

## Wyniki i ograniczenia

Każde wykonanie każdej aktywnej reguły dostaje nowy `run_id`, także przy
niezmienionych danych i tej samej wersji reguły. Trzy reguły uruchamiane codziennie
tworzą trzy osobne obiekty historii dziennie. Ponowne pobranie tego samego
`run_id` nie tworzy duplikatu. Błąd wykonania też jest osobnym wpisem historii,
ale nie ma podsumowania PASS/FAIL.

Dla domyślnego katalogu historia znajduje się w:

- `workspace.dq_control.dq_runs`: identyfikator wykonania, reguła, daty, status,
  wersja SQL i źródeł, ewentualny błąd wykonania;
- `workspace.dq_control.dq_results`: liczby PASS/FAIL połączone przez `run_id`;
- `workspace.dq_control.dq_errors`: błędne rekordy połączone przez `run_id`.

**Pobierz wszystkie wyniki** pokazuje liczbę nowych i wcześniej pobranych
checków, najnowszą datę w chmurze oraz lokalizację historii. Niekompletny wynik
jest zgłaszany z identyfikatorem i nie blokuje pozostałych wykonań. Po poprawieniu
problemu kolejne pobranie ponowi tylko brakujące importy. Raport pokazuje
wykonania od najnowszej daty, z nazwą reguły, statusem i zdalnym `run_id`.

Jeśli job ma status SUCCESS, ale brakuje nowych raportów, wykonaj w SQL Editor:

```sql
SELECT r.run_id, r.rule_key, r.started_at, r.completed_at, r.status,
       s.passed, s.failed, r.execution_error
FROM workspace.dq_control.dq_runs r
LEFT JOIN workspace.dq_control.dq_results s ON s.run_id = r.run_id
ORDER BY r.started_at DESC;
```

Brak nowych wierszy w `dq_runs` oznacza, że nie ma nowych wykonań do pobrania
z tej lokalizacji. Sprawdź parametry zadania, ścieżkę notebooka i jego końcową
komórkę wywołującą `run_job`. Sam komunikat o zakończeniu joba nie potwierdza
wykonania checków.

- `dq_runs` zapisuje wykonanie jednej reguły i wersje Delta wszystkich użytych tabel; `dq_results` liczby PASS/FAIL; `dq_errors` błędne rekordy. Pobieranie nie duplikuje historii.
- Reguła pozostaje dostępna lokalnie po wysłaniu. Chmura wykonuje ostatnią opublikowaną wersję; po edycji wyślij ją ponownie. Wyłączenie reguły dla harmonogramu również wymaga wysłania zmiany.
- SQL jest tłumaczony z SQLite do Databricks i sprawdzany w chmurze przed publikacją. Nie każda funkcja SQL jest przenośna. W pierwszej wersji krótkie nazwy muszą należeć do jednego katalogu i schematu profilu; źródła chmurowe dla reguł muszą być tabelami Delta.
- Upload oraz ręczne wykonanie mają limit 100 000 rekordów / 50 MB. Notebook może przetwarzać większe źródła; pobieranie szczegółów błędów zachowuje swoje limity.
- Import zachowuje istniejący całkowitoliczbowy, unikalny `id`. Jeśli źródło nie ma `id`, lokalna kopia otrzymuje identyfikator techniczny. Wysyłanie tej kopii przenosi też ten identyfikator. Przy wykonaniu na oryginalnej tabeli chmurowej użyj w SQL istniejącego klucza źródła `AS id`; program nie zgaduje klucza ani nie zmienia nazw kolumn po cichu.
- Import zachowuje logiczne typy `BIGINT`, `INT`, `STRING`, `BOOLEAN`, `DATE`,
  `TIMESTAMP`, `TIMESTAMP_NTZ` oraz `DECIMAL(p,s)` z precyzją i skalą. Lokalny
  techniczny klucz `id` pozostaje `INTEGER`. Daty i czas są walidowane jako ISO;
  nowe wartości BOOLEAN muszą być 0/1 lub true/false. CSV korzysta z tych samych
  typów i odrzuca wartości, które do nich nie pasują.
- SQLite nie ma natywnego przechowywania dat ani stałoprzecinkowych liczb DECIMAL.
  Daty/czas przechowujemy bez zmiany wartości jako tekst ISO, BOOLEAN jako 0/1,
  a DECIMAL jako dokładny tekst. Deklaracje magazynowe `"DECIMAL(10,2) TEXT"`
  i `"STRING TEXT"` zapobiegają zaokrągleniom i utracie zer w identyfikatorach;
  aplikacja pokazuje typy logiczne `DECIMAL(10,2)` i `STRING`. Typy nie zmieniają
  SQLite w silnik Databricks: obliczenia dziesiętne w lokalnym SQL nadal podlegają
  zasadom SQLite. Upload odtwarza typy Databricks i wysyła daty/Decimal jako
  odpowiednie wartości Pythona.
- Dopasowanie istniejącej tabeli tworzy kopię zapasową i sprawdza zachowanie
  każdego rekordu, identyfikatorów oraz zależności. Domyślnie błędne wartości
  blokują całą zmianę. Jawny tryb zachowania anomalii pozwala zmienić deklaracje
  bez naprawiania istniejących błędnych danych DQ; nowe importy nadal są walidowane.
- Zamknięcie aplikacji może przerwać ręczny transfer/test. Zaplanowany notebook działa niezależnie. Testy lokalne nie zastępują pierwszego wykonania na Twoim koncie Databricks.
