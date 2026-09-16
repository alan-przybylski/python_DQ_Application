import tkinter as tk
from tkinter import ttk, messagebox

from config.i18n import tr, AppError
from logic.accounts import ROLES, list_users, normalize_role, password_checks, save_user
from logic.login_functions import deactivate_user
from ui.common import header, footer, error_box, table_view
from ui.utils import place_window


class AdminWindow:
    def __init__(self, root, username, role, dashboard_root, time_var):
        self.root, self.username, self.role = root, username, role
        self.dashboard_root, self.time_var = dashboard_root, time_var
        place_window(root)
        root.title("DQ Studio / " + tr("User management"))
        header(root, "User management", username)
        footer(root, self.go_back, time_var)
        root.protocol("WM_DELETE_WINDOW", self.go_back)
        actions = tk.Frame(root)
        actions.pack(fill="x", padx=20, pady=16)
        tk.Button(actions, text=tr("Create user"), command=self.add_user).pack(
            side="left", padx=4
        )
        tk.Button(actions, text=tr("Modify user"), command=self.change_password).pack(
            side="left", padx=4
        )
        tk.Button(
            actions, text=tr("Deactivate user"), command=self.deactivate_user
        ).pack(side="left", padx=4)
        frame, self.tree = table_view(
            root,
            [
                ("username", "Username", 360),
                ("role", "Role", 220),
                ("active", "Active", 150),
            ],
            10,
        )
        frame.pack(fill="both", expand=True, padx=24, pady=16)
        self.refresh_users()

    def refresh_users(self):
        self.users = list_users(self.username)
        self.tree.delete(*self.tree.get_children())
        for username, role, active in self.users:
            self.tree.insert(
                "",
                "end",
                values=(username, normalize_role(role), "✓" if active else "—"),
            )

    def go_back(self):
        self.root.destroy()
        self.dashboard_root.deiconify()

    def add_user(self):
        self.user_form(create=True)

    def change_password(self):
        self.user_form(create=False)

    def user_form(self, create=False, deactivate=False):
        self.refresh_users()
        win = tk.Toplevel(self.root)
        place_window(win)
        win.transient(self.root)
        title = (
            "Create user"
            if create
            else "Deactivate user"
            if deactivate
            else "Modify user"
        )
        win.title(tr(title))
        header(win, title)
        footer(win, win.destroy)
        body = tk.Frame(win)
        body.pack(expand=True, padx=24, pady=12)
        tk.Label(body, text=tr("Username")).grid(row=0, column=0, sticky="w", pady=5)
        selected = tk.StringVar()
        if create:
            entry = tk.Entry(body, textvariable=selected, width=36)
        else:
            entry = ttk.Combobox(
                body,
                textvariable=selected,
                values=[row[0] for row in self.users],
                state="readonly",
                width=34,
            )
        entry.grid(row=1, column=0, sticky="ew")
        role_var = tk.StringVar(value="user")
        active_var = tk.BooleanVar(value=True)
        tk.Label(body, text=tr("Role")).grid(row=2, column=0, sticky="w", pady=(12, 4))
        roles = ttk.Combobox(
            body,
            textvariable=role_var,
            values=ROLES,
            state="disabled" if deactivate else "readonly",
            width=34,
        )
        roles.grid(row=3, column=0, sticky="ew")
        active_box = tk.Checkbutton(body, text=tr("Active"), variable=active_var)
        active_box.grid(row=4, column=0, sticky="w", pady=4)
        if deactivate:
            active_box.configure(state="disabled")
        password_var = tk.StringVar()
        if not deactivate:
            tk.Label(
                body,
                text=tr(
                    "Password"
                    if create
                    else "New password (leave empty to keep current)"
                ),
            ).grid(row=5, column=0, sticky="w", pady=(8, 4))
            tk.Entry(body, textvariable=password_var, show="*", width=36).grid(
                row=6, column=0, sticky="ew"
            )
            checklist = tk.Label(body, justify="left", anchor="w", font=("Segoe UI", 9))
            checklist.grid(row=7, column=0, sticky="w", pady=8)

            def update_checks(*args):
                checklist.configure(
                    text="\n".join(
                        ("✓ " if passed else "✗ ") + tr(label)
                        for label, passed in password_checks(password_var.get())[:3]
                    )
                )

            password_var.trace_add("write", update_checks)
            update_checks()

        def load_selected(event=None):
            record = next((row for row in self.users if row[0] == selected.get()), None)
            if record:
                role_var.set(normalize_role(record[1]))
                active_var.set(False if deactivate else bool(record[2]))

        if not create and self.users:
            chosen = self.tree.selection()
            selected.set(
                self.tree.item(chosen[0], "values")[0] if chosen else self.users[0][0]
            )
            entry.bind("<<ComboboxSelected>>", load_selected)
            load_selected()

        def submit():
            try:
                if deactivate:
                    deactivate_user(selected.get(), actor=self.username)
                else:
                    save_user(
                        selected.get(),
                        password_var.get() if create or password_var.get() else None,
                        role_var.get(),
                        active_var.get(),
                        actor=self.username,
                        create=create,
                    )
                try:
                    self.refresh_users()
                except AppError:
                    messagebox.showinfo(
                        tr("Success"),
                        tr("Your permissions changed. Please sign in again."),
                        parent=win,
                    )
                    win.destroy()
                    self.go_back()
                    if hasattr(self.dashboard_root, "dq_sign_out"):
                        self.dashboard_root.dq_sign_out()
                    return
                messagebox.showinfo(
                    tr("Success"),
                    tr("User created." if create else "Changes saved."),
                    parent=win,
                )
                win.destroy()
            except Exception as error:
                error_box(error, win)

        tk.Button(
            body,
            text=tr(title if create or deactivate else "Save changes"),
            command=submit,
        ).grid(row=8, column=0, sticky="ew", pady=8)

    def deactivate_user(self):
        self.user_form(create=False, deactivate=True)
