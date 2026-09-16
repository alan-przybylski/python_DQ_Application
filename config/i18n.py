"""Application-owned text; database values and user SQL are never translated."""

import json

from config.paths import DATA_DIR

SETTINGS_PATH = DATA_DIR / "settings.json"
_language = "EN"
PL = {
    "Run not found.": "Nie znaleziono uruchomienia.",
    "Your permissions changed. Please sign in again.": "Twoje uprawnienia się zmieniły. Zaloguj się ponownie.",
    "Select a column": "Wybierz kolumnę",
    "Choose a .csv filename.": "Wybierz nazwę pliku z rozszerzeniem .csv.",
    "An export cannot overwrite the import file currently being used.": "Eksport nie może nadpisać aktualnie używanego pliku importu.",
    "Demo mode uses a separate database. New demo login: demo / Demo2026. Existing passwords are unchanged.": "Tryb demo używa osobnej bazy. Login nowego demo: demo / Demo2026. Istniejące hasła pozostają bez zmian.",
    "Demo — synthetic data only": "Demo — wyłącznie fikcyjne dane",
    "Language": "Język",
    "Back": "Wstecz",
    "Close": "Zamknij",
    "Exit": "Wyjdź",
    "Sign in": "Zaloguj się",
    "Sign out": "Wyloguj się",
    "Username": "Login",
    "Password": "Hasło",
    "Welcome back": "Witaj ponownie",
    "Make data quality visible.": "Zobacz jakość swoich danych.",
    "Sign in to your local workspace.": "Zaloguj się do lokalnego obszaru roboczego.",
    "Import CSV / SQL rules / Persistent results": "Import CSV / Reguły SQL / Historia wyników",
    "Local SQLite workspace": "Lokalna przestrzeń SQLite",
    "Workspace": "Obszar roboczy",
    "Your data. A clearer picture.": "Twoje dane. Pełniejszy obraz.",
    "Import CSV": "Import CSV",
    "Rules & quality results": "Reguły i wyniki jakości",
    "Import history": "Historia importów",
    "Manage users": "Zarządzaj użytkownikami",
    "Export table": "Eksport tabeli",
    "User management": "Zarządzanie użytkownikami",
    "Create user": "Utwórz użytkownika",
    "Modify user": "Edytuj użytkownika",
    "Deactivate user": "Dezaktywuj użytkownika",
    "Select user": "Wybierz użytkownika",
    "Role": "Rola",
    "Active": "Aktywne",
    "Save changes": "Zapisz zmiany",
    "New password (leave empty to keep current)": "Nowe hasło (puste pole zachowuje obecne)",
    "At least 6 characters": "Minimum 6 znaków",
    "At least one uppercase letter": "Minimum jedna duża litera",
    "At least one digit": "Minimum jedna cyfra",
    "At most 72 UTF-8 bytes": "Maksymalnie 72 bajty UTF-8",
    "Password requirements": "Wymagania hasła",
    "Password does not meet: {requirements}": "Hasło nie spełnia wymagań: {requirements}",
    "Username is required.": "Login jest wymagany.",
    "Invalid role.": "Nieprawidłowa rola.",
    "A superuser account is required.": "Wymagane jest aktywne konto superuser.",
    "User not found.": "Nie znaleziono użytkownika.",
    "Account is inactive.": "Konto jest nieaktywne.",
    "Incorrect password.": "Nieprawidłowe hasło.",
    "Username already exists.": "Taki login już istnieje.",
    "The last active superuser cannot be deactivated or demoted.": "Nie można dezaktywować ani obniżyć uprawnień ostatniego aktywnego superusera.",
    "Changes saved.": "Zapisano zmiany.",
    "User created.": "Utworzono użytkownika.",
    "Error": "Błąd",
    "Success": "Gotowe",
    "Warning": "Uwaga",
    "Confirm": "Potwierdź",
    "Database error: {detail}": "Błąd bazy danych: {detail}",
    "Operation failed: {detail}": "Operacja nie powiodła się: {detail}",
    "Choose CSV file": "Wybierz plik CSV",
    "CSV files": "Pliki CSV",
    "All files": "Wszystkie pliki",
    "Existing table": "Istniejąca tabela",
    "Create a new table": "Utwórz nową tabelę",
    "Table": "Tabela",
    "Table name": "Nazwa tabeli",
    "Choose file": "Wybierz plik",
    "Download CSV template": "Pobierz szablon CSV",
    "Preview": "Podgląd",
    "Import": "Importuj",
    "Create table only": "Utwórz samą tabelę",
    "Add column": "Dodaj kolumnę",
    "Remove column": "Usuń kolumnę",
    "Column name": "Nazwa kolumny",
    "Type": "Typ",
    "Required": "Wymagane",
    "Source column": "Kolumna w CSV",
    "Target column": "Kolumna docelowa",
    "Ignore": "Pomiń",
    "Apply column": "Zapisz kolumnę",
    "Columns / mapping": "Kolumny / dopasowanie",
    "No file selected": "Nie wybrano pliku",
    "Select a table.": "Wybierz tabelę.",
    "Select a CSV file first.": "Najpierw wybierz plik CSV.",
    "Select or add a column.": "Wybierz lub dodaj kolumnę.",
    "Identifiers must start with a letter or underscore and contain only letters, digits and underscores.": "Nazwy muszą zaczynać się literą lub podkreśleniem i zawierać tylko litery, cyfry oraz podkreślenia.",
    "This table name is reserved.": "Ta nazwa tabeli jest zarezerwowana.",
    "Table already exists.": "Tabela już istnieje.",
    "Table does not exist.": "Tabela nie istnieje.",
    "At least one column is required.": "Wymagana jest przynajmniej jedna kolumna.",
    "Column names must be unique.": "Nazwy kolumn muszą być unikalne.",
    "Supported types: TEXT, INTEGER, REAL.": "Obsługiwane typy: TEXT, INTEGER, REAL.",
    "The id column must be INTEGER or TEXT.": "Kolumna id musi mieć typ INTEGER lub TEXT.",
    "CSV headers must be nonempty and unique.": "Nagłówki CSV muszą być niepuste i unikalne.",
    "CSV has no header.": "CSV nie zawiera nagłówka.",
    "CSV has no data rows.": "CSV nie zawiera wierszy danych.",
    "CSV row {row} has a different number of fields.": "Wiersz {row} w CSV ma inną liczbę pól.",
    "Map every CSV column or explicitly ignore it.": "Dopasuj każdą kolumnę CSV albo jawnie ją pomiń.",
    "Multiple source columns map to the same target.": "Kilka kolumn źródłowych wskazuje tę samą kolumnę docelową.",
    "Unknown column: {column}": "Nieznana kolumna: {column}",
    "Missing required column: {column}": "Brak wymaganej kolumny: {column}",
    "No columns selected for import.": "Nie wybrano kolumn do importu.",
    "Row {row}, {column}: {detail}": "Wiersz {row}, {column}: {detail}",
    "A value is required.": "Wartość jest wymagana.",
    "Expected an integer.": "Oczekiwano liczby całkowitej.",
    "Expected a finite number using a decimal point.": "Oczekiwano skończonej liczby z kropką dziesiętną.",
    "Duplicate id in the CSV.": "Powtórzony identyfikator id w CSV.",
    "Import rejected. No data was saved.\n{details}": "Import odrzucony. Niczego nie zapisano.\n{details}",
    "Imported {count} rows into {table}. All changes committed together.": "Zaimportowano {count} wierszy do {table}. Wszystkie zmiany zapisano razem.",
    "Table created: {table}": "Utworzono tabelę: {table}",
    "Rows with matching id update existing records; missing generated id creates a new record.": "Wiersze z pasującym id aktualizują rekordy; brak generowanego id tworzy nowy rekord.",
    "If no id column is defined, an INTEGER id is generated automatically.": "Jeśli nie zdefiniujesz kolumny id, identyfikator INTEGER zostanie dodany automatycznie.",
    "Preview: {count} rows. Showing the first {shown}.": "Podgląd: {count} wierszy. Wyświetlono pierwsze {shown}.",
    "Export CSV": "Eksport CSV",
    "Export errors": "Eksport błędów",
    "Save CSV": "Zapisz CSV",
    "Protect spreadsheet formulas": "Zabezpiecz formuły arkusza",
    "Exported {count} rows.": "Wyeksportowano {count} wierszy.",
    "Overwrite the selected file?": "Nadpisać wybrany plik?",
    "Template saved.": "Zapisano szablon.",
    "Quality report": "Raport jakości",
    "Run checks": "Uruchom sprawdzanie",
    "Refresh": "Odśwież",
    "Run": "Uruchomienie",
    "Latest run": "Ostatnie uruchomienie",
    "No runs yet": "Brak uruchomień",
    "Pass rate": "Odsetek poprawnych",
    "Checks": "Sprawdzenia",
    "Failed checks": "Błędne sprawdzenia",
    "Rules completed": "Wykonane reguły",
    "Quality over time": "Jakość w czasie",
    "Failed records for this run": "Błędne rekordy z tego uruchomienia",
    "Search errors": "Szukaj błędów",
    "No failed records in this run.": "Brak błędnych rekordów w tym uruchomieniu.",
    "Legacy results have no run id. Run checks to start linked history.": "Starsze wyniki nie mają numeru uruchomienia. Uruchom sprawdzanie, aby rozpocząć powiązaną historię.",
    "No results yet": "Brak wyników",
    "Record": "Rekord",
    "Field": "Pole",
    "Value": "Wartość",
    "Rule": "Reguła",
    "Message": "Komunikat",
    "Details": "Szczegóły",
    "Date": "Data",
    "All rules": "Wszystkie reguły",
    "Single rule": "Jedna reguła",
    "Choose a rule": "Wybierz regułę",
    "No active rules": "Brak aktywnych reguł",
    "No rule selected.": "Nie wybrano reguły.",
    "completed": "zakończone",
    "partial": "częściowe",
    "failed": "błąd wykonania",
    "no_rules": "brak reguł",
    "Run #{run_id}: {passed} passed, {failed} failed; {errors} execution errors.": "Uruchomienie #{run_id}: {passed} poprawnych, {failed} błędnych; {errors} błędów wykonania.",
    "Execution errors: {details}": "Błędy wykonania: {details}",
    "Rule SQL must be read-only and may access only dataset tables.": "SQL reguły musi być tylko do odczytu i może korzystać wyłącznie z tabel danych.",
    "Rule output must contain id, the tested field as the second column, and dq_check (0 or 1).": "Wynik reguły musi zawierać id, sprawdzane pole jako drugą kolumnę oraz dq_check (0 lub 1).",
    "Rule record id cannot be empty.": "Identyfikator rekordu reguły nie może być pusty.",
    "DQ check failed": "Sprawdzenie DQ nie powiodło się",
    "DQ check passed": "Sprawdzenie DQ poprawne",
    "Rule library": "Biblioteka reguł",
    "Add rule": "Dodaj regułę",
    "Deactivate rule": "Dezaktywuj regułę",
    "Modify rule": "Edytuj regułę",
    "Active rules": "Aktywne reguły",
    "Archived rules": "Archiwum reguł",
    "Description": "Opis",
    "Rule type": "Typ reguły",
    "Error message": "Komunikat błędu",
    "SQL query": "Zapytanie SQL",
    "Version": "Wersja",
    "Status": "Status",
    "Created": "Utworzono",
    "Select a rule.": "Wybierz regułę.",
    "Rule not found.": "Nie znaleziono reguły.",
    "Description and rule type are required.": "Opis i typ reguły są wymagane.",
    "Deactivate the rule before modifying it.": "Przed edycją dezaktywuj regułę.",
    "Rule deactivated and archived.": "Reguła została dezaktywowana i zarchiwizowana.",
    "Rule saved.": "Zapisano regułę.",
    "File": "Plik",
    "Rows": "Wiersze",
    "Imported by": "Zaimportował",
    "Local data is not published on GitHub.": "Lokalne dane nie są publikowane na GitHubie.",
}


def tr(message, **values):
    return (PL.get(message, message) if _language == "PL" else message).format(**values)


def language():
    return _language


def set_language(value, persist=True):
    global _language
    if value not in {"PL", "EN"}:
        raise ValueError("Language must be PL or EN")
    _language = value
    if persist:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps({"language": value}), encoding="utf-8")


def load_language():
    try:
        set_language(
            json.loads(SETTINGS_PATH.read_text(encoding="utf-8")).get("language", "EN"),
            persist=False,
        )
    except OSError, ValueError, TypeError:
        set_language("EN", persist=False)


class AppError(ValueError):
    def __init__(self, message, **values):
        self.message, self.values = message, values
        super().__init__(message)

    def __str__(self):
        return tr(self.message, **self.values)
