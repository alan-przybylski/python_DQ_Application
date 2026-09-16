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
            (1,'1.1','Name required','required','customers','SELECT id,name,1 AS dq_check FROM customers');
        INSERT INTO dq_rules(id,version,status,description,rule_type,target_table,sql_query) VALUES
            (2,'1.0','INACTIVE','Name required','required','customers','SELECT id,name,1 AS dq_check FROM customers');
        INSERT INTO dq_rules_history(rule_id,version,description,rule_type,target_table,rule_params,deactivated_by) VALUES
            (2,'1.0','Name required','required','customers','{"sql_query":"SELECT id,name,1 AS dq_check FROM customers","error_message":"Missing name"}','demo');
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
        dashboard_module.DashboardWindow(root, "demo", "admin")
        check_window(root, "02_dashboard")
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
        assert rules.tree.xview()[1] < 1.0, (
            "Wide rule columns must be horizontally scrollable."
        )
        assert rules.archive_tree.xview()[1] < 1.0
        rules.add_rule_window()
        dialog = [w for w in rules_root.winfo_children() if isinstance(w, tk.Toplevel)][
            -1
        ]
        check_window(dialog, "08_add_rule")
        dialog.destroy()
        rules.archive_tree.selection_set(rules.archive_tree.get_children()[0])
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
        importer.go_back()
        from ui.export_window import ExportWindow

        export_root = tk.Toplevel(root)
        exporter = ExportWindow(export_root, "demo", "superuser", root, clock_var)
        check_window(export_root, "15_export")
        exporter.go_back()
        assert len(captured) == 15
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
            "SELECT id, amount, CASE WHEN amount>0 THEN 1 ELSE 0 END AS dq_check FROM orders",
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
