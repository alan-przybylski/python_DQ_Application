"""Reviewable remote rule publication and asynchronous result synchronization."""

import difflib
import json
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from config.i18n import tr
from database.connection import get_connection, dict_row_factory
from integrations.databricks_contract import revision
from logic.databricks_profiles import load_profiles
from logic.databricks_sync import mappings, save_mapping, compare, publish, accept_remote, setup_remote, synchronize
from logic.databricks_manual import run_remote_checks
from ui.common import header, footer, error_box
from ui.utils import place_window


class DatabricksSyncWindow:
    def __init__(self, root, username, role, dashboard_root, time_var):
        self.root,self.username,self.role,self.parent = root,username,role,dashboard_root
        self.cancel = threading.Event()
        self.events = queue.Queue()
        self.busy = False
        self.review = None
        place_window(root,1200,800)
        root.resizable(True,True)
        root.title('DQ Studio / '+tr('Databricks sync'))
        header(root,'Databricks sync',username)
        footer(root,self.close,time_var)
        root.protocol('WM_DELETE_WINDOW',self.close)
        profiles = load_profiles()
        self.profile_data = profiles['profiles']
        c = get_connection()
        c.row_factory = dict_row_factory
        self.rules = c.execute('SELECT * FROM dq_rules ORDER BY id').fetchall()
        c.close()
        form = tk.Frame(root)
        form.pack(fill='x',padx=24,pady=8)
        form.columnconfigure(1,weight=1)
        self.rule_choice = tk.StringVar()
        self.rule_picker = ttk.Combobox(form,textvariable=self.rule_choice,state='readonly',
            values=[f"{r['id']} · {r['description']}" for r in self.rules])
        tk.Label(form,text=tr('Rule')).grid(row=0,column=0,sticky='w')
        self.rule_picker.grid(row=0,column=1,sticky='ew',pady=4)
        self.rule_picker.bind('<<ComboboxSelected>>',self.load_rule)
        self.profile = tk.StringVar(value=profiles['selected'])
        tk.Label(form,text=tr('Connection profile')).grid(row=1,column=0,sticky='w')
        ttk.Combobox(form,textvariable=self.profile,values=list(self.profile_data),state='readonly').grid(row=1,column=1,sticky='ew',pady=4)
        selected = self.profile_data.get(profiles['selected'],{})
        self.fields = {}
        for row,(key,label,default) in enumerate([
            ('control_catalog','DQ catalog',selected.get('catalog','workspace')),
            ('control_schema','DQ schema','dq_control'),
            ('source_catalog','Source catalog',selected.get('catalog','workspace')),
            ('source_schema','Source schema',selected.get('schema','default')),
            ('source_table','Source table / view',selected.get('table','')),
        ],2):
            var = tk.StringVar(value=default)
            self.fields[key]=var
            tk.Label(form,text=tr(label)).grid(row=row,column=0,sticky='w',padx=(0,16))
            tk.Entry(form,textvariable=var).grid(row=row,column=1,sticky='ew',pady=2)
        self.auto = tk.BooleanVar(value=False)
        tk.Checkbutton(form,text=tr('Download results after sign-in'),variable=self.auto).grid(row=7,column=1,sticky='w')
        tk.Label(root,text=tr('Spark SQL: use {{{{source}}}} for the mapped Delta table; return a source key AS id, the checked field, and dq_check.'),
                 anchor='w',wraplength=1120).pack(fill='x',padx=24,pady=4)
        self.sql = tk.Text(root,height=7,font=('Consolas',10),undo=True,wrap='none')
        self.sql.pack(fill='both',expand=True,padx=24,pady=4)
        bar = tk.Frame(root)
        bar.pack(fill='x',padx=24,pady=4)
        self.buttons=[]
        for label,action in [('Save mapping',self.save),('Prepare DQ tables',self.prepare),('Compare definitions',self.compare),('Download all results',self.download),('Run selected in Databricks',self.run_selected),('Run all in Databricks',self.run_all)]:
            button=tk.Button(bar,text=tr(label),command=action)
            button.grid(row=len(self.buttons)//3,column=len(self.buttons)%3,sticky='ew',padx=4,pady=3)
            bar.columnconfigure(len(self.buttons)%3,weight=1)
            self.buttons.append(button)
        self.status=tk.StringVar(value=tr('Publication is explicit. Results download never runs checks on your computer.'))
        tk.Label(root,textvariable=self.status,anchor='w',wraplength=1120,justify='left').pack(fill='x',padx=24,pady=8)
        if self.rules:
            self.rule_picker.current(0)
            self.load_rule()
        self.poll_id=root.after(100,self.poll)

    def load_rule(self,event=None):
        if self.busy:
            return
        rule=self.rules[self.rule_picker.current()]
        link=next((l for l in mappings() if l['rule_id']==rule['id']),None)
        self.sql.delete('1.0','end')
        if link:
            self.profile.set(link['profile'])
            for key,var in self.fields.items(): var.set(link[key])
            self.auto.set(bool(link['auto_sync']))
            self.sql.insert('1.0',link['remote_sql'])
            self.status.set(link['last_error'] or (tr('Last sync')+': '+str(link['last_sync'] or '—')))
        else:
            query=rule['sql_query'] or 'SELECT product_id AS id, sku, 0 AS dq_check FROM {{source}};'
            query=re.sub(r'\bFROM\s+(?:"'+re.escape(rule['target_table'])+r'"|'+re.escape(rule['target_table'])+r')\b', 'FROM {{source}}',query,flags=re.I)
            c=get_connection()
            columns={r[1] for r in c.execute('PRAGMA table_info("'+rule['target_table'].replace('"','""')+'")')}
            c.close()
            if 'product_id' in columns:
                query=re.sub(r'^(\s*SELECT\s+)id\s*,',r'\1product_id AS id,',query,flags=re.I)
            self.sql.insert('1.0',query)
        self.review=None

    def link_id(self):
        if self.rule_picker.current()<0:
            raise ValueError('Select a rule.')
        rid=self.rules[self.rule_picker.current()]['id']
        link=next((l for l in mappings() if l['rule_id']==rid),None)
        if not link: raise ValueError('Save the mapping first.')
        return link['id']

    def save(self):
        try:
            if self.rule_picker.current()<0: raise ValueError('Select a rule.')
            save_mapping(self.rules[self.rule_picker.current()]['id'],self.username,self.profile.get(),
                         **{k:v.get().strip() for k,v in self.fields.items()},remote_sql=self.sql.get('1.0','end-1c'),auto_sync=self.auto.get())
            self.review=None
            self.status.set(tr('Mapping saved. Compare definitions before publishing.'))
            return True
        except Exception as error:
            error_box(error,self.root)
            return False

    def start(self,operation,callback=None):
        if self.busy: return
        self.busy=True
        for button in self.buttons: button.configure(state='disabled')
        self.rule_picker.configure(state='disabled')
        self.status.set(tr('Connecting to Databricks… Browser sign-in may be required.'))
        def worker():
            try: self.events.put((True,operation(),callback))
            except Exception as error: self.events.put((False,str(error),None))
        threading.Thread(target=worker,daemon=True).start()

    def prepare(self):
        if not self.save(): return
        link=self.link_id()
        if messagebox.askyesno(tr('Confirm'),tr('Create the dedicated DQ schema and control tables in Databricks?'),parent=self.root):
            self.start(lambda: setup_remote(link,self.username))

    def compare(self):
        if not self.save(): return
        link=self.link_id()
        self.start(lambda: compare(link),lambda result:self.show_review(link,result))

    def show_review(self,link,comparison):
        win=tk.Toplevel(self.root)
        place_window(win)
        win.title(tr('Compare definitions'))
        header(win,'Compare definitions')
        footer(win,win.destroy)
        text=tk.Text(win,font=('Consolas',10),wrap='word')
        text.pack(fill='both',expand=True,padx=24,pady=12)
        remote=json.dumps(comparison['remote'],indent=2,ensure_ascii=False).splitlines()
        local=json.dumps(comparison['local'],indent=2,ensure_ascii=False).splitlines()
        diff='\n'.join(difflib.unified_diff(remote,local,fromfile='Databricks',tofile='Local draft',lineterm=''))
        text.insert('1.0',diff or tr('Definitions are identical.'))
        text.configure(state='disabled')
        bar=tk.Frame(win)
        bar.pack(fill='x',padx=24,pady=8)
        def send():
            win.destroy()
            self.start(lambda:publish(link,self.username,revision(comparison['local']),comparison['remote_revision']))
        def receive():
            win.destroy()
            self.start(lambda:accept_remote(link,self.username,comparison['remote_revision']),lambda _:self.load_rule())
        tk.Button(bar,text=tr('Publish to Databricks'),command=send).pack(side='left',padx=4)
        tk.Button(bar,text=tr('Use remote definition'),command=receive,state='normal' if comparison['remote'] else 'disabled').pack(side='left',padx=4)

    def download(self):
        self.start(lambda:synchronize(self.username,cancel=self.cancel),lambda n:self.status.set(tr('Imported {count} remote checks.',count=n)))

    def run_selected(self):
        try:
            link=self.link_id()
        except Exception as error:
            error_box(error,self.root)
            return
        self.run_remote(link)

    def run_all(self):
        self.run_remote()

    def run_remote(self,link=None):
        self.start(lambda:run_remote_checks(self.username,link,cancel=self.cancel),
                   lambda n:self.status.set(tr('Executed and imported {count} Databricks checks.',count=n)))

    def poll(self):
        try: ok,value,callback=self.events.get_nowait()
        except queue.Empty: pass
        else:
            self.busy=False
            for button in self.buttons: button.configure(state='normal')
            self.rule_picker.configure(state='readonly')
            self.status.set(tr('Done.') if ok else value)
            if ok and callback: callback(value)
        self.poll_id=self.root.after(100,self.poll)

    def close(self):
        self.cancel.set()
        self.root.after_cancel(self.poll_id)
        self.root.destroy()
        self.parent.deiconify()


def startup_sync(root,username,status):
    """One background sync per login; no Tk calls from the worker."""
    cancel=threading.Event()
    if not any(l['auto_sync'] and l['execution_mode']=='databricks' for l in mappings()):
        return cancel
    events=queue.Queue()
    status.set(tr('Synchronizing Databricks results…'))
    def worker():
        try: events.put((True,synchronize(username,auto_only=True,cancel=cancel)))
        except Exception as error: events.put((False,str(error)))
    def poll():
        if cancel.is_set(): return
        try: ok,value=events.get_nowait()
        except queue.Empty: root.after(200,poll)
        else: status.set(tr('Imported {count} remote checks.',count=value) if ok else tr('Databricks sync failed: {detail}',detail=value))
    threading.Thread(target=worker,daemon=True).start()
    root.after(200,poll)
    return cancel
