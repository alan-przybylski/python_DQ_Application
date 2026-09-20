"""Open each real Tk window against an isolated SQLite database.

Run explicitly with DQ_GUI_TESTS=1 on a machine with an interactive desktop.
Optional DQ_CAPTURE_DIR saves application-window-only screenshots.
"""

import importlib
import os
from pathlib import Path
import tkinter as tk

import pytest


pytestmark = [
    pytest.mark.gui,
    pytest.mark.skipif(
        os.environ.get("DQ_GUI_TESTS") != "1",
        reason="Set DQ_GUI_TESTS=1 to open GUI windows.",
    ),
]


@pytest.fixture(scope="module")
def tkinter_root():
    # The application uses one Tk interpreter and multiple Toplevel windows.
    # Reuse that lifecycle while checking both display sizes.
    root = tk.Tk()
    try:
        yield root
    finally:
        root.destroy()


@pytest.mark.parametrize("language", ["EN", "PL"])
@pytest.mark.parametrize("screen_size", [(1920, 1080), (1366, 768)])
def test_every_window_has_shared_geometry_and_visible_controls(
    monkeypatch, screen_size, language, sqlite_database, tkinter_root
):
    from config.i18n import set_language, tr

    set_language(language, persist=False)
    from database.connection import get_connection
    from tkinter import messagebox

    connection = get_connection()
    connection.executescript("""
        INSERT INTO users(username,password_hash,role) VALUES('demo','test-only','superuser');
        INSERT INTO dq_rules(id,version,description,rule_type,target_table,sql_query) VALUES
            (1,'1.1','Name required','required','customers','SELECT id,name,0 AS dq_check FROM customers');
        INSERT INTO dq_rules(id,version,status,description,rule_type,target_table,sql_query) VALUES
            (2,'1.0','INACTIVE','Name required','required','customers','SELECT id,name,0 AS dq_check FROM customers');
        INSERT INTO dq_rules_history(rule_id,version,description,rule_type,target_table,rule_params,deactivated_by) VALUES
            (2,'1.0','Name required','required','customers','{"sql_query":"SELECT id,name,0 AS dq_check FROM customers","error_message":"Missing name"}','demo');
        INSERT INTO dq_results(rule_id,rule_version,passed_count,failed_count,timestamp) VALUES
            (1,'1.1',8,2,'2026-09-14 12:00:00'),(1,'1.1',9,1,'2026-09-15 12:00:00');
        INSERT INTO data_load_log(table_name,file_name,row_count,loaded_by) VALUES('customers','example.csv',12,'demo');
    """)
    connection.close()
    monkeypatch.setattr(tk.Misc, "winfo_screenwidth", lambda self: screen_size[0])
    monkeypatch.setattr(tk.Misc, "winfo_screenheight", lambda self: screen_size[1])

    def unexpected_error(*args, **kwargs):
        raise AssertionError(f"Unexpected message box: {args}")

    monkeypatch.setattr(messagebox, "showerror", unexpected_error)
    monkeypatch.setattr(messagebox, "showinfo", lambda *args, **kwargs: None)
    callback_errors = []
    root = tkinter_root
    root.report_callback_exception = lambda *error: callback_errors.append(error)
    clock_var = tk.StringVar(master=root, value="12:00:00")
    expected_size = (min(1100, screen_size[0] - 40), min(720, screen_size[1] - 100))
    captured = []

    def check_window(window, label):
        window.lift()
        window.update_idletasks()
        window.update()
        redraw_complete = tk.BooleanVar(master=window, value=False)
        window.after(150, redraw_complete.set, True)
        window.wait_variable(redraw_complete)
        assert (window.winfo_width(), window.winfo_height()) == expected_size, label
        assert tuple(map(int, window.resizable())) == (0, 0), label

        def descendants(parent):
            for widget in parent.winfo_children():
                if isinstance(widget, tk.Toplevel):
                    continue
                yield widget
                yield from descendants(widget)

        for widget in descendants(window):
            if widget.winfo_class() in {"Menu", "Frame", "Canvas"}:
                continue
            if not widget.winfo_manager():
                continue  # Import mode intentionally hides the alternative name input.
            from tkinter import ttk

            ancestor = widget
            hidden_tab = False
            while ancestor is not window and ancestor.master is not None:
                parent = ancestor.master
                if (
                    isinstance(parent, ttk.Notebook)
                    and str(ancestor) != parent.select()
                ):
                    hidden_tab = True
                    break
                ancestor = parent
            if hidden_tab:
                continue
            assert widget.winfo_viewable(), (label, widget.winfo_class(), "not mapped")
            x = widget.winfo_rootx() - window.winfo_rootx()
            y = widget.winfo_rooty() - window.winfo_rooty()
            assert x >= 0 and y >= 0, (label, widget.winfo_class(), x, y)
            assert x + widget.winfo_width() <= expected_size[0], (
                label,
                widget.winfo_class(),
                "right",
            )
            assert y + widget.winfo_height() <= expected_size[1], (
                label,
                widget.winfo_class(),
                "bottom",
            )

        capture_dir = os.environ.get("DQ_CAPTURE_DIR")
        if capture_dir and screen_size == (1920, 1080):
            from PIL import ImageGrab

            destination = Path(capture_dir)
            destination.mkdir(parents=True, exist_ok=True)
            image = ImageGrab.grab(window=window.winfo_id())
            image.save(destination / f"{label}.png")
        captured.append(label)

    try:
        login_module = importlib.import_module("ui.login_window")
        login_module.LoginWindow(root)
        check_window(root, "01_login")
        for widget in root.winfo_children():
            widget.destroy()

        dashboard_module = importlib.import_module("ui.dashboard_window")
        dashboard = dashboard_module.DashboardWindow(root, "demo", "admin")
        check_window(root, "02_dashboard")
        dashboard.open_quality_report()
        report_window = [
            w for w in root.winfo_children() if isinstance(w, tk.Toplevel)
        ][-1]
        report_window.update()
        assert root.state() == "withdrawn"
        report_window.tk.call(report_window.protocol("WM_DELETE_WINDOW"))
        assert root.state() == "normal"
        for callback_id in root.tk.splitlist(root.tk.call("after", "info")):
            root.after_cancel(callback_id)

        admin_module = importlib.import_module("ui.admin_window")
        admin_root = tk.Toplevel(root)
        admin = admin_module.AdminWindow(admin_root, "demo", "admin", root, clock_var)
        check_window(admin_root, "03_admin")
        for method_name, label in [
            ("add_user", "04_add_user"),
            ("change_password", "05_change_password"),
            ("deactivate_user", "06_deactivate_user"),
        ]:
            getattr(admin, method_name)()
            dialog = [
                w for w in admin_root.winfo_children() if isinstance(w, tk.Toplevel)
            ][-1]
            check_window(dialog, label)
            dialog.destroy()
        admin.go_back()

        rules_module = importlib.import_module("ui.data_quality")
        rules_root = tk.Toplevel(root)
        rules = rules_module.DataQualityWindow(
            rules_root, "demo", "admin", root, clock_var
        )
        check_window(rules_root, "07_rules")
        assert len(rules.tree.get_children()) == 2
        assert "version" not in rules.tree["columns"]
        assert not hasattr(rules, "archive_tree")
        rules.add_rule_window()
        dialog = [w for w in rules_root.winfo_children() if isinstance(w, tk.Toplevel)][
            -1
        ]
        check_window(dialog, "08_add_rule")
        dialog.destroy()
        rules.tree.selection_set("2")
        rules.modify_dq_rule()
        dialog = [w for w in rules_root.winfo_children() if isinstance(w, tk.Toplevel)][
            -1
        ]
        check_window(dialog, "09_modify_rule")

        def descendants(parent):
            for child in parent.winfo_children():
                yield child
                yield from descendants(child)

        next(
            widget
            for widget in descendants(dialog)
            if isinstance(widget, tk.Button)
            and widget.cget("text") == tr("Save changes")
        ).invoke()
        connection = get_connection()
        assert connection.execute(
            "SELECT version,status FROM dq_rules WHERE id=2"
        ).fetchone() == ("1.1", "ACTIVE")
        connection.close()

        rules.tree.selection_set("2")
        rules.open_rule()
        details = rules.details
        for index, label in enumerate(
            ("18_rule_definition", "19_rule_results", "20_rule_versions")
        ):
            details.notebook.select(index)
            check_window(details.root, label)
        assert len(details.data["versions"]) == 2
        details.version_picker.current(1)
        details.compare.set(True)
        details.show_version()
        assert details.version_text.get("1.0", "end-1c")
        details.close()

        check_module = importlib.import_module("ui.check_dq_panel")
        check_root = tk.Toplevel(rules_root)
        panel = check_module.CheckDqPanel(
            check_root, "demo", "admin", rules_root, clock_var
        )
        check_window(check_root, "10_dq_results")
        panel.open_dq_dialog()
        dialog = [w for w in check_root.winfo_children() if isinstance(w, tk.Toplevel)][
            -1
        ]
        check_window(dialog, "11_run_rules")
        panel.run_type.set("all")
        panel.on_run_type_change()
        assert str(panel.rule_dropdown.cget("state")) == "disabled"
        panel.run_type.set("single")
        panel.on_run_type_change()
        assert str(panel.rule_dropdown.cget("state")) == "readonly"
        dialog.destroy()
        panel.go_back()
        rules.go_back()

        history_module = importlib.import_module("ui.file_history")
        history_root = tk.Toplevel(root)
        history = history_module.FileHistory(
            history_root, "demo", "admin", root, clock_var
        )
        check_window(history_root, "12_file_history")
        history.go_back()
        from ui.import_window import ImportWindow

        import_root = tk.Toplevel(root)
        importer = ImportWindow(import_root, "demo", "superuser", root, clock_var)
        check_window(import_root, "13_import_existing")
        importer.mode.set("new")
        importer.change_mode()
        check_window(import_root, "14_import_new")
        importer.open_databricks()
        dialog = [
            w for w in import_root.winfo_children() if isinstance(w, tk.Toplevel)
        ][-1]
        check_window(dialog, "16_databricks")
        # Exercise WM close path, including poll cancellation and parent restoration.
        dialog.tk.call(dialog.protocol("WM_DELETE_WINDOW"))
        importer.open_table_editor()
        dialog = [
            w for w in import_root.winfo_children() if isinstance(w, tk.Toplevel)
        ][-1]
        check_window(dialog, "17_table_editor")
        dialog.tk.call(dialog.protocol("WM_DELETE_WINDOW"))
        importer.go_back()
        from ui.export_window import ExportWindow

        export_root = tk.Toplevel(root)
        exporter = ExportWindow(export_root, "demo", "superuser", root, clock_var)
        check_window(export_root, "15_export")
        exporter.go_back()
        assert len(captured) == 20
        assert not callback_errors, callback_errors
    finally:
        set_language("EN", persist=False)
        for callback_id in root.tk.splitlist(root.tk.call("after", "info")):
            root.after_cancel(callback_id)
        for widget in root.winfo_children():
            widget.destroy()


def test_import_new_table_rule_and_report_workflow(
    monkeypatch, sqlite_database, tkinter_root, tmp_path
):
    from tkinter import filedialog, messagebox, ttk
    from config.i18n import set_language
    from logic.accounts import save_user
    from logic.datasets import list_tables, read_csv
    from database.connection import get_connection
    from ui.import_window import ImportWindow
    from ui.data_quality import DataQualityWindow
    from ui.check_dq_panel import CheckDqPanel
    from ui.admin_window import AdminWindow

    set_language("EN", persist=False)
    save_user("admin", "Admin123", "superuser", create=True)
    root = tkinter_root
    clock = tk.StringVar(master=root, value="TEST")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    monkeypatch.setattr(
        messagebox, "showerror", lambda *args, **kwargs: errors.append(args)
    )
    monkeypatch.setattr(messagebox, "showinfo", lambda *args, **kwargs: None)
    source = tmp_path / "orders.csv"
    source.write_text("order_code;amount\n001;12\n002;-5\n", encoding="utf-8")
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **kwargs: str(source))

    def descendants(parent):
        for child in parent.winfo_children():
            yield child
            yield from descendants(child)

    def click(parent, label):
        next(
            widget
            for widget in descendants(parent)
            if isinstance(widget, tk.Button) and widget.cget("text") == label
        ).invoke()

    try:
        importer = ImportWindow(tk.Toplevel(root), "admin", "superuser", root, clock)
        importer.mode.set("new")
        importer.change_mode()
        importer.new_name.set("orders")
        importer.choose_file()
        assert importer.columns[0]["type"] == "TEXT"
        importer.import_file()
        assert importer.mode.get() == "existing"
        assert "orders" in list_tables()
        connection = get_connection()
        assert connection.execute(
            "SELECT id,order_code,amount FROM orders ORDER BY id"
        ).fetchall() == [(1, "001", 12), (2, "002", -5)]
        connection.close()
        importer.go_back()

        rules = DataQualityWindow(tk.Toplevel(root), "admin", "superuser", root, clock)
        rules.add_rule_window()
        dialog = next(
            w for w in rules.root.winfo_children() if isinstance(w, tk.Toplevel)
        )
        rules.form_table.set("orders")
        selector = next(w for w in descendants(dialog) if isinstance(w, ttk.Combobox))
        selector.event_generate("<<ComboboxSelected>>")
        text_widget = next(w for w in descendants(dialog) if isinstance(w, tk.Text))
        assert 'FROM "orders"' in text_widget.get("1.0", "end")
        entries = [
            w
            for w in descendants(dialog)
            if isinstance(w, tk.Entry) and not isinstance(w, ttk.Combobox)
        ]
        for widget, value in zip(
            entries, ("Positive amount", "range", "Amount must be positive")
        ):
            widget.insert(0, value)
        text_widget.delete("1.0", "end")
        text_widget.insert(
            "1.0",
            "SELECT id, amount, CASE WHEN amount>0 THEN 0 ELSE 1 END AS dq_check FROM orders",
        )
        click(dialog, "Save changes")

        panel = CheckDqPanel(tk.Toplevel(root), "admin", "superuser", root, clock)
        first = panel.run_all_dq_rules("orders")
        assert panel.current["id"] == first
        assert panel.metrics["failed"].get() == "1"
        assert len(panel.error_tree.get_children()) == 1
        panel.search.set("does not match")
        assert len(panel.error_tree.get_children()) == 0
        panel.search.set("Amount")
        assert len(panel.error_tree.get_children()) == 1
        export = tmp_path / "errors.csv"
        monkeypatch.setattr(
            "ui.check_dq_panel.save_csv_dialog", lambda *args: str(export)
        )
        panel.export_current()
        assert len(read_csv(export).rows) == 1
        connection = get_connection()
        with connection:
            connection.execute("UPDATE orders SET amount=5 WHERE id=2")
        connection.close()
        panel.run_all_dq_rules("orders")
        assert panel.metrics["failed"].get() == "0"
        assert len(panel.error_tree.get_children()) == 0
        panel.run_selector.current(1)
        panel.select_run()
        assert panel.current["id"] == first
        assert len(panel.error_tree.get_children()) == 1
        panel.go_back()
        rules.go_back()

        admin = AdminWindow(tk.Toplevel(root), "admin", "superuser", root, clock)
        admin.add_user()
        dialog = next(
            w for w in admin.root.winfo_children() if isinstance(w, tk.Toplevel)
        )
        entries = [
            w
            for w in descendants(dialog)
            if isinstance(w, tk.Entry) and not isinstance(w, ttk.Combobox)
        ]
        entries[0].insert(0, "analyst")
        entries[1].insert(0, "Analyst1")
        role_selector = next(
            w for w in descendants(dialog) if isinstance(w, ttk.Combobox)
        )
        role_selector.set("superuser")
        click(dialog, "Create user")
        assert ("analyst", "superuser", 1) in admin.users
        admin.go_back()
        assert not errors, errors
    finally:
        for widget in root.winfo_children():
            widget.destroy()


def test_databricks_download_save_refresh_and_schema_edit_ui(
    monkeypatch, sqlite_database, tkinter_root
):
    from tkinter import messagebox
    from config.i18n import set_language
    from database.connection import get_connection
    from logic.databricks_import import Source, Snapshot, local_columns
    from logic.datasets import table_columns
    from ui.databricks_window import DatabricksWindow
    from ui.table_editor import TableEditor
    import ui.databricks_window as module

    set_language("EN", persist=False)
    root = tkinter_root
    messages = []
    monkeypatch.setattr(
        messagebox, "showinfo", lambda *args, **kwargs: messages.append(args)
    )
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        messagebox, "showerror", lambda *args, **kwargs: pytest.fail(str(args))
    )
    source = Source(
        "dbc-test.cloud.databricks.com",
        "/sql/1.0/warehouses/123",
        "workspace",
        "default",
        "customers",
    )
    rows = [(8, "Ada"), (8, "Bob")]

    def fake_download(actual, limit, cancel):
        assert actual == source
        return Snapshot(
            source, local_columns([("id", "int"), ("name", "string")]), list(rows)
        )

    monkeypatch.setattr(module, "download", fake_download)
    window = tk.Toplevel(root)
    importer = DatabricksWindow(window, "admin", root, lambda: None)
    for key, variable in importer.fields.items():
        variable.set(getattr(source, key))

    def complete_download():
        importer.start_download()
        done = tk.BooleanVar(master=root, value=False)
        attempts = 0

        def wait():
            nonlocal attempts
            attempts += 1
            if importer.snapshot is not None or attempts > 100:
                done.set(True)
            else:
                root.after(20, wait)

        root.after(20, wait)
        root.wait_variable(done)
        assert importer.snapshot is not None

    def data():
        connection = get_connection()
        try:
            return connection.execute("SELECT * FROM ui_snapshot").fetchall()
        finally:
            connection.close()

    try:
        complete_download()
        assert len(importer.preview.get_children()) == 2
        importer.target.set("ui_snapshot")
        importer.save()
        assert data() == [(1, 8, "Ada"), (2, 8, "Bob")]
        rows[:] = [(9, "New")]
        complete_download()
        importer.replace.set(True)
        importer.target_mode()
        importer.target.set("ui_snapshot")
        # A rejected confirmation must not call the write service.
        monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: False)
        importer.save()
        assert len(data()) == 2
        monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)
        importer.save()
        assert data() == [(1, 9, "New")]
        complete_download()
        importer.fields["table"].set("different")
        assert importer.snapshot is None
        assert str(importer.save_button["state"]) == "disabled"
        importer.go_back()

        edit_root = tk.Toplevel(root)
        editor = TableEditor(edit_root, "admin", root, lambda: None, "ui_snapshot")
        editor.name.set("country")
        editor.kind.set("TEXT")
        editor.apply("add")
        assert table_columns("ui_snapshot")[-1]["name"] == "country"
        editor.tree.selection_set("3")
        editor.select()
        editor.name.set("country_code")
        editor.apply("modify")
        assert table_columns("ui_snapshot")[-1]["name"] == "country_code"
        editor.tree.selection_set("3")
        editor.select()
        editor.apply("drop")
        assert len(table_columns("ui_snapshot")) == 3
        editor.go_back()
        assert messages
    finally:
        for widget in root.winfo_children():
            widget.destroy()


def test_closing_databricks_window_during_download_is_safe(
    monkeypatch, sqlite_database, tkinter_root
):
    import threading
    import ui.databricks_window as module
    from config.i18n import AppError
    from logic.datasets import list_tables

    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def delayed(source, limit, cancel):
        entered.set()
        try:
            assert release.wait(3)
            assert cancel.is_set()
            raise AppError("Download cancelled. No local data was changed.")
        finally:
            finished.set()

    monkeypatch.setattr(module, "download", delayed)
    root = tkinter_root
    window = tk.Toplevel(root)
    importer = module.DatabricksWindow(window, "admin", root, lambda: None)
    values = dict(
        hostname="dbc-test.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/123",
        catalog="workspace",
        schema="default",
        table="customers",
    )
    for name, value in values.items():
        importer.fields[name].set(value)
    try:
        importer.start_download()
        assert entered.wait(2)
        importer.go_back()
        assert all(not variable.trace_info() for variable in importer.fields.values())
        release.set()
        assert finished.wait(2)
        root.update()
        assert list_tables() == ["customers"]
    finally:
        release.set()
        for widget in root.winfo_children():
            widget.destroy()


def test_profiles_survive_reopening_and_switch_without_authentication(
    monkeypatch, sqlite_database, tkinter_root
):
    from tkinter import messagebox
    from logic.databricks_profiles import load_profiles
    from ui.databricks_window import DatabricksWindow

    root = tkinter_root
    monkeypatch.setattr(
        messagebox, "showerror", lambda *args, **kwargs: pytest.fail(str(args))
    )
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)
    first = DatabricksWindow(tk.Toplevel(root), "admin", root, lambda: None)
    settings = dict(
        hostname="dbc-test.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/123",
        catalog="workspace",
        schema="default",
        table="customers",
    )
    try:
        for key, value in settings.items():
            first.fields[key].set(value)
        first.profile_name.set("My test")
        first.save_connection_profile()
        first.profile_name.set("Other source")
        first.fields["table"].set("orders")
        first.save_connection_profile()
        first.profile_name.set("My test")
        first.use_profile()
        assert first.fields["table"].get() == "customers"
        first.go_back()

        second = DatabricksWindow(tk.Toplevel(root), "admin", root, lambda: None)
        assert second.profile_name.get() == "My test"
        assert {key: var.get() for key, var in second.fields.items()} == settings
        second.fields["table"].set("modified")
        monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: False)
        second.save_connection_profile()
        assert load_profiles()["profiles"]["My test"]["table"] == "customers"
        monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)
        second.save_connection_profile()
        assert load_profiles()["profiles"]["My test"]["table"] == "modified"
        second.delete_connection_profile()
        assert list(load_profiles()["profiles"]) == ["Other source"]
        assert second.fields["hostname"].get() == ""
        second.go_back()
    finally:
        for widget in root.winfo_children():
            widget.destroy()


def test_unified_rules_filter_history_and_actions(
    monkeypatch, sqlite_database, tkinter_root
):
    from tkinter import messagebox
    from config.i18n import set_language, tr
    from database.connection import get_connection
    from ui.data_quality import DataQualityWindow

    set_language("EN", persist=False)
    connection = get_connection()
    connection.executescript("""
        INSERT INTO dq_rules(id,version,status,description,rule_type,target_table,sql_query) VALUES
        (1,'1.1','ACTIVE','Name required','required','customers','SELECT id,name,0 AS dq_check FROM customers'),
        (2,'1.0','INACTIVE','Other check','test','orders','SELECT id,name,0 AS dq_check FROM customers');
        INSERT INTO dq_rules_history(rule_id,version,description,rule_type,target_table,rule_params) VALUES
        (1,'1.0','Old name','required','customers','{"sql_query":"SELECT id,name,1 AS dq_check FROM customers"}');
        INSERT INTO dq_results(rule_id,rule_version,passed_count,failed_count) VALUES(1,'1.0',10,0);
    """)
    connection.close()
    root = tkinter_root
    monkeypatch.setattr(
        messagebox, "showerror", lambda *args, **kwargs: pytest.fail(str(args))
    )
    monkeypatch.setattr(messagebox, "askyesno", lambda *args, **kwargs: True)
    library = DataQualityWindow(
        tk.Toplevel(root), "admin", "superuser", root, tk.StringVar(master=root)
    )
    try:
        assert len(library.tree.get_children()) == 2
        assert library.tree.set("1", "kpi") == tr("No results")
        library.tree.set("1", "kpi", "100.0%")
        library.tree.set("2", "kpi", "9.0%")
        library.treeview_sort_column(library.tree, "kpi", False)
        assert library.tree.get_children() == ("2", "1")
        library.search.set("NAME")
        library.render_rules()
        assert library.tree.get_children() == ("1",)
        library.search.set("")
        library.status_filter.set(tr("Inactive"))
        library.render_rules()
        assert library.tree.get_children() == ("2",)
        library.status_filter.set(tr("All statuses"))
        library.table_filter.set("customers")
        library.render_rules()
        assert library.tree.get_children() == ("1",)
        library.tree.selection_set("1")
        library.open_rule()
        details = library.details
        details.notebook.select(2)
        details.version_picker.current(1)
        details.compare.set(True)
        details.show_version()
        diff = details.version_text.get("1.0", "end")
        assert "-SELECT id,name,1" in diff and "+SELECT id,name,0" in diff
        assert details.version_text.tag_ranges("added")
        assert details.version_text.tag_ranges("removed")
        details.deactivate()
        assert library.tree.set("1", "kpi") == "—"
        connection = get_connection()
        try:
            assert connection.execute(
                "SELECT status FROM dq_rules WHERE id=1"
            ).fetchone() == ("INACTIVE",)
            assert connection.execute("SELECT COUNT(*) FROM dq_results").fetchone() == (
                1,
            )
        finally:
            connection.close()
    finally:
        library.go_back()


@pytest.mark.parametrize("role", ["user", "superuser"])
def test_delete_button_visibility_by_role(
    monkeypatch, sqlite_database, tkinter_root, role
):
    from tkinter import messagebox
    from config.i18n import tr, set_language
    from database.connection import get_connection
    from ui.data_quality import DataQualityWindow

    set_language("EN", persist=False)
    connection = get_connection()
    with connection:
        connection.execute(
            "INSERT INTO users(username,password_hash,role) VALUES('actor','test',?)",
            (role,),
        )
        connection.execute(
            "INSERT INTO dq_rules(id,version,rule_type,target_table,sql_query) VALUES(1,'1.0','test','customers','SELECT id,name,1 AS dq_check FROM customers')"
        )
    connection.close()
    root = tkinter_root
    library = DataQualityWindow(
        tk.Toplevel(root), "actor", role, root, tk.StringVar(master=root)
    )
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: errors.append(a))
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)

    def descendants(parent):
        for child in parent.winfo_children():
            yield child
            yield from descendants(child)

    try:
        library.tree.selection_set("1")
        library.open_rule()
        details = library.details
        buttons = [
            w
            for w in descendants(details.root)
            if isinstance(w, tk.Button)
            and w.cget("text") == tr("Delete rule permanently")
        ]
        assert len(buttons) == (1 if role == "superuser" else 0)
        if role == "user":
            # Calling the callback directly must not bypass the service check.
            details.delete()
            assert errors and "superuser" in str(errors)
            assert details.root.winfo_exists()
            connection = get_connection()
            try:
                assert connection.execute(
                    "SELECT COUNT(*) FROM dq_rules"
                ).fetchone() == (1,)
            finally:
                connection.close()
    finally:
        library.go_back()


def test_permanent_delete_only_in_details_and_confirmation(
    monkeypatch, sqlite_database, tkinter_root
):
    from tkinter import messagebox
    from config.i18n import tr, set_language
    from database.connection import get_connection
    from logic.dq_engine import run_checks
    from ui.data_quality import DataQualityWindow

    set_language("EN", persist=False)
    connection = get_connection()
    connection.executescript("""
        INSERT INTO users(username,password_hash,role) VALUES('admin','test','superuser');
        INSERT INTO customers(name) VALUES('Ada');
        INSERT INTO dq_rules(id,version,rule_type,target_table,sql_query) VALUES
        (1,'1.0','test','customers','SELECT id,name,1 AS dq_check FROM customers');
    """)
    connection.close()
    run_checks("customers", "admin")
    root = tkinter_root
    library = DataQualityWindow(
        tk.Toplevel(root), "admin", "superuser", root, tk.StringVar(master=root)
    )
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: pytest.fail(str(a)))
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)

    def descendants(parent):
        for child in parent.winfo_children():
            yield child
            yield from descendants(child)

    try:
        assert not any(
            isinstance(w, tk.Button) and w.cget("text") == tr("Delete rule permanently")
            for w in descendants(library.root)
        )
        library.tree.selection_set("1")
        library.open_rule()
        details = library.details
        button = next(
            w
            for w in descendants(details.root)
            if isinstance(w, tk.Button)
            and w.cget("text") == tr("Delete rule permanently")
        )
        confirmations = []

        def cancel(*args, **kwargs):
            confirmations.append(kwargs)
            return False

        monkeypatch.setattr(messagebox, "askyesno", cancel)
        button.invoke()
        assert details.root.winfo_exists()
        assert confirmations[0]["default"] == "no"
        assert library.tree.exists("1")
        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
        button.invoke()
        assert not details.root.winfo_exists()
        assert not library.tree.get_children()
        connection = get_connection()
        try:
            for table in ("dq_rules", "dq_results", "dq_field_results", "dq_runs"):
                assert connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone() == (0,)
            assert connection.execute("SELECT COUNT(*) FROM customers").fetchone() == (
                1,
            )
        finally:
            connection.close()
    finally:
        library.go_back()
