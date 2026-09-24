"""Language and non-secret connection preferences, independent of importing data."""
import tkinter as tk
from tkinter import ttk, messagebox

from config.i18n import tr, language, set_language
from logic.databricks_profiles import load_profiles, save_profile, select_profile, delete_profile
from ui.common import header, footer, error_box
from ui.utils import place_window


class SettingsWindow:
    def __init__(self, root, username, role, parent, time_var):
        self.root, self.parent, self.username, self.time_var = root, parent, username, time_var
        place_window(root)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.render()

    def render(self):
        for widget in self.root.winfo_children():
            widget.destroy()
        self.root.title('DQ Studio / ' + tr('Settings'))
        header(self.root, 'Settings', self.username)
        footer(self.root, self.close, self.time_var)
        body = tk.Frame(self.root)
        body.pack(fill='both', expand=True, padx=28, pady=16)
        lang = tk.Frame(body)
        lang.pack(fill='x', pady=(0, 15))
        tk.Label(lang, text=tr('Language')).pack(side='left')
        self.language = tk.StringVar(value=language())
        ttk.Combobox(lang, textvariable=self.language, values=['EN', 'PL'], state='readonly', width=6).pack(side='left', padx=12)
        tk.Button(lang, text=tr('Apply language'), command=self.apply_language).pack(side='left')
        tk.Label(body, text=tr('Connection profile'), font=('Segoe UI', 13, 'bold')).pack(anchor='w')
        self.profile = tk.StringVar()
        self.picker = ttk.Combobox(body, textvariable=self.profile)
        self.picker.pack(fill='x', pady=8)
        self.picker.bind('<<ComboboxSelected>>', self.load)
        form = tk.Frame(body)
        form.pack(fill='x')
        form.columnconfigure(1, weight=1)
        self.fields = {}
        for row, (key, caption) in enumerate([('hostname', 'Server hostname'), ('http_path', 'HTTP path'), ('catalog', 'Catalog'), ('schema', 'Schema'), ('table', 'Source table / view')]):
            tk.Label(form, text=tr(caption)).grid(row=row, column=0, sticky='w', padx=(0, 14), pady=4)
            self.fields[key] = tk.StringVar()
            tk.Entry(form, textvariable=self.fields[key]).grid(row=row, column=1, sticky='ew', pady=4)
        buttons = tk.Frame(body)
        buttons.pack(fill='x', pady=12)
        for label, action in [('Save profile', self.save), ('Use profile', self.use), ('Delete profile', self.delete)]:
            tk.Button(buttons, text=tr(label), command=action).pack(side='left', padx=(0, 8))
        self.status = tk.StringVar(value=tr('Browser sign-in. Read-only source. No credentials saved by DQ Studio.'))
        tk.Label(body, textvariable=self.status, wraplength=900, justify='left').pack(anchor='w', pady=8)
        self.refresh()

    def refresh(self):
        saved = load_profiles()
        self.picker.configure(values=list(saved['profiles']))
        self.profile.set(saved['selected'])
        self.load()

    def load(self, event=None):
        settings = load_profiles()['profiles'].get(self.profile.get(), {})
        for key, value in self.fields.items():
            value.set(settings.get(key, ''))

    def save(self):
        try:
            name = self.profile.get().strip()
            exists = any(key.casefold() == name.casefold() for key in load_profiles()['profiles'])
            if exists and not messagebox.askyesno(tr('Confirm'), tr('Replace saved settings for profile {name}?', name=name), parent=self.root):
                return
            save_profile(name, {key: value.get() for key, value in self.fields.items()}, overwrite=exists)
            self.refresh()
            self.status.set(tr('Profile saved locally. Passwords and tokens are not stored.'))
        except Exception as error:
            error_box(error, self.root)

    def use(self):
        try:
            select_profile(self.profile.get())
            self.status.set(tr('Selected profile: {name}', name=self.profile.get()))
        except Exception as error:
            error_box(error, self.root)

    def delete(self):
        try:
            name = self.profile.get()
            if not messagebox.askyesno(tr('Confirm'), tr('Delete profile {name}? Imported tables and DQ history will remain.', name=name), parent=self.root):
                return
            delete_profile(name)
            self.refresh()
            self.status.set(tr('Profile deleted. Imported data was not changed.'))
        except Exception as error:
            error_box(error, self.root)

    def apply_language(self):
        try:
            # Keep unsaved connection fields while translating this window.
            profile = self.profile.get()
            fields = {key: value.get() for key, value in self.fields.items()}
            set_language(self.language.get())
            self.render()
            self.profile.set(profile)
            for key, value in fields.items():
                self.fields[key].set(value)
        except Exception as error:
            error_box(error, self.root)

    def close(self):
        self.root.destroy()
        refresh = getattr(self.parent, 'dq_refresh_menu', None)
        if refresh:
            refresh()
        self.parent.deiconify()
