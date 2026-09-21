"""Download on a worker; all Tk calls and confirmed writes stay on the UI thread."""

import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from config.i18n import tr, AppError
from logic.databricks_import import Source, download, save_snapshot
from logic.datasets import list_tables
from logic.databricks_profiles import (
    load_profiles,
    save_profile,
    select_profile,
    delete_profile,
)
from ui.common import header, footer, table_view, error_box
from ui.utils import place_window


class DatabricksWindow:
    def __init__(self, root, username, parent, on_close):
        self.root, self.username, self.parent, self.on_close = (
            root,
            username,
            parent,
            on_close,
        )
        self.snapshot, self.busy, self.poll_id = None, False, None
        self.events, self.cancel = queue.Queue(), threading.Event()
        place_window(root)
        root.title("DQ Studio / Databricks")
        header(root, "Import from Databricks", username)
        footer(root, self.go_back)
        root.protocol("WM_DELETE_WINDOW", self.go_back)
        profiles = tk.Frame(root)
        profiles.pack(fill="x", padx=24, pady=(6, 0))
        tk.Label(profiles, text=tr("Connection profile")).pack(
            side="left", padx=(0, 10)
        )
        self.profile_name = tk.StringVar()
        self.profile_picker = ttk.Combobox(
            profiles, textvariable=self.profile_name, width=24
        )
        self.profile_picker.pack(side="left", padx=(0, 10))
        self.profile_picker.bind("<<ComboboxSelected>>", self.use_profile)
        self.profile_buttons = []
        for label, command in [
            ("Save profile", self.save_connection_profile),
            ("Delete profile", self.delete_connection_profile),
        ]:
            button = tk.Button(profiles, text=tr(label), command=command)
            button.pack(side="left", padx=4)
            self.profile_buttons.append(button)
        form = tk.Frame(root)
        form.pack(fill="x", padx=24, pady=8)
        form.columnconfigure(1, weight=1)
        self.fields, self.inputs = {}, []
        for row, (key, label, default) in enumerate(
            [
                ("hostname", "Server hostname", ""),
                ("http_path", "HTTP path", ""),
                ("catalog", "Catalog", ""),
                ("schema", "Schema", "default"),
                ("table", "Source table / view", ""),
            ]
        ):
            tk.Label(form, text=tr(label)).grid(
                row=row, column=0, sticky="w", padx=(0, 16), pady=2
            )
            variable = tk.StringVar(value=default)
            entry = tk.Entry(form, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            variable.trace_add("write", self.invalidate)
            self.fields[key] = variable
            self.inputs.append(entry)
        tools = tk.Frame(root)
        tools.pack(fill="x", padx=24, pady=4)
        tk.Label(tools, text=tr("Maximum rows")).pack(side="left")
        self.limit = tk.StringVar(value="10000")
        self.limit.trace_add("write", self.invalidate)
        limit_entry = tk.Entry(tools, textvariable=self.limit, width=9)
        limit_entry.pack(side="left", padx=10)
        self.inputs.append(limit_entry)
        self.download_button = tk.Button(
            tools, text=tr("Sign in and download preview"), command=self.start_download
        )
        self.download_button.pack(side="left", padx=6)
        self.cancel_button = tk.Button(
            tools,
            text=tr("Cancel download"),
            command=self.cancel_download,
            state="disabled",
        )
        self.cancel_button.pack(side="right")
        self.status = tk.StringVar(
            value=tr(
                "Browser sign-in. Read-only source. No credentials saved by DQ Studio."
            )
        )
        tk.Label(
            root, textvariable=self.status, anchor="w", wraplength=1020, justify="left"
        ).pack(fill="x", padx=24, pady=4)
        frame, self.preview = table_view(root, [], 4)
        frame.pack(fill="both", expand=True, padx=24, pady=4)
        self.mapping = tk.StringVar(
            value=tr(
                "Local id is generated. Source id becomes source_id; decimals and dates are stored as text."
            )
        )
        tk.Label(
            root, textvariable=self.mapping, wraplength=1020, anchor="w", justify="left"
        ).pack(fill="x", padx=24, pady=4)
        target = tk.Frame(root)
        target.pack(fill="x", padx=24, pady=4)
        self.replace = tk.BooleanVar()
        self.target = tk.StringVar()
        for label, value in [
            ("New local table", False),
            ("Replace local snapshot", True),
        ]:
            tk.Radiobutton(
                target,
                text=tr(label),
                variable=self.replace,
                value=value,
                command=self.target_mode,
            ).pack(side="left", padx=(0, 8))
        tk.Label(target, text=tr("Local table")).pack(side="left", padx=(4, 0))
        self.target_entry = ttk.Combobox(
            target, textvariable=self.target, values=list_tables(), width=24
        )
        self.target_entry.pack(side="left", padx=8)
        self.save_button = tk.Button(
            target, text=tr("Save locally"), command=self.save, state="disabled"
        )
        self.save_button.pack(side="right")
        tk.Label(
            root,
            text=tr(
                "Refresh replaces local rows only. Old DQ results stay unchanged; local row ids may change."
            ),
            anchor="w",
            wraplength=1020,
        ).pack(fill="x", padx=24, pady=(0, 4))
        try:
            saved = self.refresh_profiles()
            name = saved["selected"]
            if name:
                self.profile_name.set(name)
                self.fill_profile(saved["profiles"][name])
        except Exception as error:
            error_box(error, self.root)

    def refresh_profiles(self):
        saved = load_profiles()
        self.profile_picker.configure(
            values=sorted(saved["profiles"], key=str.casefold)
        )
        return saved

    def fill_profile(self, settings):
        for key, value in settings.items():
            self.fields[key].set(value)
        self.status.set(
            tr(
                "Profile loaded. Sign in to download; saved settings are not a login session."
            )
        )

    def use_profile(self, event=None):
        if self.busy:
            return
        try:
            self.fill_profile(select_profile(self.profile_name.get()))
        except Exception as error:
            error_box(error, self.root)

    def save_connection_profile(self):
        if self.busy:
            return
        try:
            name = self.profile_name.get().strip()
            saved = load_profiles()
            existing = any(n.casefold() == name.casefold() for n in saved["profiles"])
            if existing and not messagebox.askyesno(
                tr("Confirm"),
                tr("Replace saved settings for profile {name}?", name=name),
                parent=self.root,
            ):
                return
            save_profile(
                name,
                {key: value.get() for key, value in self.fields.items()},
                overwrite=existing,
            )
            self.refresh_profiles()
            self.profile_name.set(name)
            self.status.set(
                tr("Profile saved locally. Passwords and tokens are not stored.")
            )
        except Exception as error:
            error_box(error, self.root)

    def delete_connection_profile(self):
        if self.busy:
            return
        try:
            name = self.profile_name.get()
            if name not in load_profiles()["profiles"]:
                raise AppError("Select a saved profile.")
            if not messagebox.askyesno(
                tr("Confirm"),
                tr(
                    "Delete profile {name}? Imported tables and DQ history will remain.",
                    name=name,
                ),
                parent=self.root,
            ):
                return
            delete_profile(name)
            self.refresh_profiles()
            self.profile_name.set("")
            for variable in self.fields.values():
                variable.set("")
            self.status.set(tr("Profile deleted. Imported data was not changed."))
        except Exception as error:
            error_box(error, self.root)

    def target_mode(self):
        self.target_entry.configure(
            state="readonly" if self.replace.get() else "normal", values=list_tables()
        )
        self.target.set(self.fields['table'].get() if not self.replace.get() else '')

    def invalidate(self, *args):
        self.snapshot = None
        if hasattr(self, "save_button"):
            self.save_button.configure(state="disabled")
            self.preview.delete(*self.preview.get_children())
            self.status.set(
                tr("Connection details changed. Download again before saving.")
            )

    def start_download(self):
        if self.busy:
            return
        try:
            source = Source(
                **{key: value.get().strip() for key, value in self.fields.items()}
            )
            source.validate()
            if not self.replace.get():
                self.target.set(source.table)
            try:
                limit = int(self.limit.get())
            except ValueError:
                raise AppError("The row limit must be between 1 and 100000.") from None
            if not 1 <= limit <= 100000:
                raise AppError("The row limit must be between 1 and 100000.")
        except Exception as error:
            error_box(error, self.root)
            return
        self.invalidate()
        self.cancel.clear()
        self.busy = True
        for widget in [
            *self.inputs,
            self.download_button,
            self.profile_picker,
            *self.profile_buttons,
        ]:
            widget.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.status.set(
            tr(
                "Waiting for browser sign-in / downloading. You can cancel; local data is unchanged."
            )
        )
        events, cancel = self.events, self.cancel

        def worker():
            try:
                events.put((True, download(source, limit, cancel,preserve_names=True)))
            except Exception as error:
                events.put((False, error))

        threading.Thread(target=worker, daemon=True, name="databricks-download").start()
        self.poll_id = self.root.after(100, self.poll)

    def poll(self):
        self.poll_id = None
        try:
            success, result = self.events.get_nowait()
        except queue.Empty:
            self.poll_id = self.root.after(100, self.poll)
            return
        self.busy = False
        for widget in [
            *self.inputs,
            self.download_button,
            self.profile_picker,
            *self.profile_buttons,
        ]:
            widget.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        if self.cancel.is_set():
            self.status.set(tr("Download cancelled. No local data was changed."))
            return
        if not success:
            self.status.set(str(result))
            error_box(result, self.root)
            return
        self.snapshot = result
        self.preview.delete(*self.preview.get_children())
        self.preview.configure(columns=[c["name"] for c in result.columns])
        for column in result.columns:
            name = column["name"]
            self.preview.heading(
                name, text=f"{column['source']} → {name} [{column['type']}]"
            )
            self.preview.column(name, width=220, minwidth=90, stretch=False)
        for row in result.rows[:20]:
            self.preview.insert(
                "",
                "end",
                values=["NULL" if value is None else str(value)[:200] for value in row],
            )
        self.status.set(
            tr(
                "Downloaded {count} rows. Preview shows up to 20. Nothing saved locally yet.",
                count=len(result.rows),
            )
        )
        self.save_button.configure(state="normal")

    def cancel_download(self):
        self.cancel.set()
        self.cancel_button.configure(state="disabled")
        self.status.set(
            tr(
                "Cancellation requested. Waiting for the current network operation; you may close this window."
            )
        )

    def save(self):
        if self.snapshot is None or self.busy:
            return
        try:
            table = self.target.get().strip()
            if not table:
                raise AppError("Select a table.")
            if self.replace.get():
                prompt = tr(
                    "Replace ALL rows in local table {table} with {count} downloaded rows? A database backup will be kept. DQ history will not change.",
                    table=table,
                    count=len(self.snapshot.rows),
                )
            else:
                prompt = tr(
                    "Create local table {table} with {count} rows from {source}?",
                    table=table,
                    count=len(self.snapshot.rows),
                    source=self.snapshot.source.reference,
                )
            if not messagebox.askyesno(tr("Confirm"), prompt, parent=self.root):
                return
            count, backup = save_snapshot(
                self.snapshot, table, self.username, self.replace.get()
            )
            text = tr(
                "Imported {count} rows into {table}. All changes committed together.",
                count=count,
                table=table,
            )
            if backup:
                text += "\n" + tr("Changes saved. Backup: {path}", path=backup)
            messagebox.showinfo(tr("Success"), text, parent=self.root)
            self.target_entry.configure(values=list_tables())
            self.snapshot = None
            self.save_button.configure(state="disabled")
            self.status.set(
                tr("Saved locally. Download again to obtain a new snapshot.")
            )
        except Exception as error:
            error_box(error, self.root)

    def go_back(self):
        self.cancel.set()
        if self.poll_id:
            self.root.after_cancel(self.poll_id)
        # Variable traces belong to the shared Tcl interpreter, not the Toplevel.
        # Remove them explicitly so closing cannot retain a downloaded snapshot.
        for variable in [*self.fields.values(), self.limit]:
            for mode, callback in variable.trace_info():
                variable.trace_remove(mode, callback)
        self.snapshot = None
        self.root.destroy()
        self.on_close()
        self.parent.deiconify()
