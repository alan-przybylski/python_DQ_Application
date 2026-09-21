# SQL między tabelami

Nie potrzebujesz osobnego kreatora ani rejestrowania słownika. `ref_countries` jest zwykłą tabelą, tak jak każda inna.

Zaimportuj potrzebne tabele i otwórz **SQL editor**. Pisz zwykły SQL z nazwami tabel widocznymi po lewej. Możesz używać JOIN, EXISTS, NOT EXISTS oraz CTE. Kliknij **Run SQL**, a potem **Create rule**.

Przykład sprawdzenia pary kraj–waluta (w tym przykładzie `dane` oznacza sprawdzaną tabelę; zastąp nazwę i kolumny swoimi):

```sql
SELECT d.id, d.country_code,
       CASE WHEN EXISTS (
           SELECT 1
           FROM ref_countries c
           WHERE c.country_code = d.country_code
             AND c.currency_code = d.currency_code
             AND c.active_flag = TRUE
       ) THEN 0 ELSE 1 END AS dq_check
FROM dane d;
```

`EXISTS` nie mnoży wyników, jeśli słownik ma duplikaty. Reguła przechodzi wtedy, gdy w słowniku istnieje aktywny rekord pasujący do obu wartości. NULL nie pasuje przez zwykłe `=`; jeśli chcesz inne zachowanie, zapisz je jawnie w CASE. To samo dotyczy ignorowania spacji lub wielkości liter.

Lokalnie zapytanie działa od razu. Aby wykonać je w Databricks, wyślij obie tabele pod tymi samymi nazwami, a następnie wyślij regułę. Program dopisze katalog i schemat z wybranego profilu oraz sprawdzi SQL. Szczegóły: [tabele i reguły w Databricks](DATABRICKS_SYNC.md).

Poprzedni kreator usunięto z interfejsu. Już zapisane reguły starszego typu zachowano dla zgodności; nie trzeba tworzyć takich reguł dla nowych zapytań.
