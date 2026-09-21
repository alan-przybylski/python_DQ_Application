"""A small table/rule transfer screen sharing the application's connection profile."""
import queue
import threading
import tkinter as tk
from tkinter import ttk,messagebox
from config.i18n import tr
from database.connection import get_connection
from logic.datasets import list_tables
from logic.databricks_profiles import load_profiles,select_profile
from logic.cloud_workspace import upload_table,send_rule,destination
from logic.databricks_sync import synchronize,mappings
from logic.databricks_manual import run_remote_checks
from ui.common import header,footer,error_box
from ui.utils import place_window


class CloudWindow:
    def __init__(self,root,username,role,parent,time_var,initial_table=None,initial_rule=None):
        self.root,self.username,self.parent=root,username,parent
        self.busy=False
        self.cancel=threading.Event()
        self.events=queue.Queue()
        self.closed=False
        place_window(root,1050,740)
        root.resizable(True,True)
        root.title('DQ Studio / Databricks')
        header(root,'Databricks',username)
        footer(root,self.close,time_var)
        root.protocol('WM_DELETE_WINDOW',self.close)
        body=tk.Frame(root)
        body.pack(fill='both',expand=True,padx=28,pady=14)
        settings=load_profiles()
        self.profile=tk.StringVar(root,value=settings['selected'])
        tk.Label(body,text=tr('Connection profile')).pack(anchor='w')
        profile=ttk.Combobox(body,textvariable=self.profile,values=list(settings['profiles']),state='readonly')
        profile.pack(fill='x',pady=5)
        profile.bind('<<ComboboxSelected>>',lambda event:self.profile_changed())
        self.destination=tk.StringVar(root)
        tk.Label(body,textvariable=self.destination).pack(anchor='w',pady=6)
        tk.Label(body,text=tr('Same table names here and in Databricks. Write ordinary SQL in the editor.'),wraplength=950).pack(anchor='w',pady=8)
        tk.Label(body,text=tr('Table')).pack(anchor='w')
        tables=list_tables()
        self.table=tk.StringVar(root,value=initial_table or (tables[0] if tables else ''))
        table=ttk.Combobox(body,textvariable=self.table,values=tables,state='readonly')
        table.pack(fill='x',pady=5)
        self.replace=tk.BooleanVar(root,value=False)
        self.replace_box=tk.Checkbutton(body,text=tr('Replace existing Databricks table (schema and data)'),variable=self.replace)
        self.replace_box.pack(anchor='w',pady=5)
        self.buttons=[]
        def button(parent,label,action):
            index=len(parent.winfo_children())
            b=tk.Button(parent,text=tr(label),command=action)
            b.grid(row=index//2,column=index%2,sticky='ew',padx=3,pady=4)
            parent.columnconfigure(index%2,weight=1)
            self.buttons.append(b)
        table_actions=tk.Frame(body)
        table_actions.pack(fill='x')
        button(table_actions,'Send table to Databricks',self.send_table)
        button(table_actions,'Download table from Databricks',self.download_table)
        ttk.Separator(body).pack(fill='x',pady=10)
        tk.Label(body,text=tr('Rule')).pack(anchor='w')
        c=get_connection()
        try: rules=c.execute('SELECT id,description,target_table FROM dq_rules ORDER BY id').fetchall()
        finally: c.close()
        self.rules={f'#{rid} · {description} ({table})':rid for rid,description,table in rules}
        initial=next((label for label,rid in self.rules.items() if rid==initial_rule),next(iter(self.rules),''))
        self.rule=tk.StringVar(root,value=initial)
        picker=ttk.Combobox(body,textvariable=self.rule,values=list(self.rules),state='readonly')
        picker.pack(fill='x',pady=5)
        rule_actions=tk.Frame(body)
        rule_actions.pack(fill='x')
        button(rule_actions,'Send rule to Databricks',self.send_rule)
        button(rule_actions,'Run selected in Databricks',self.run_selected)
        button(rule_actions,'Run all in Databricks',lambda:self.start(lambda:run_remote_checks(self.username,cancel=self.cancel)))
        button(rule_actions,'Download all results',lambda:self.start(lambda:synchronize(self.username,cancel=self.cancel)))
        self.status=tk.StringVar(root,value='')
        tk.Label(body,textvariable=self.status,wraplength=940,justify='left').pack(fill='x',pady=12)
        self.inputs=[profile,table,picker,self.replace_box]
        self.profile_changed(save=False)
        self.poll_id=root.after(100,self.poll)

    def profile_changed(self,save=True):
        settings=load_profiles()['profiles'].get(self.profile.get(),{})
        self.destination.set('.'.join([settings.get('catalog',''),settings.get('schema','')]))
        if save and self.profile.get(): select_profile(self.profile.get())

    def send_table(self):
        try:
            profile,table,replace=self.profile.get(),self.table.get(),self.replace.get()
            source=destination(profile,table)
            if replace and not messagebox.askyesno(tr('Confirm'),tr('Replace the schema and all data in {table}?',table=source.sql_name),parent=self.root): return
            self.start(lambda:upload_table(self.username,profile,table,replace,cancel=self.cancel))
        except Exception as error: error_box(error,self.root)

    def send_rule(self):
        rid=self.rules.get(self.rule.get())
        if rid is None: return
        profile=self.profile.get()
        self.start(lambda:send_rule(self.username,profile,rid))

    def run_selected(self):
        rid=self.rules.get(self.rule.get())
        link=next((l for l in mappings() if l['rule_id']==rid),None)
        if not link:
            self.status.set(tr('Send this rule to Databricks first.'))
            return
        self.start(lambda:run_remote_checks(self.username,link['id'],cancel=self.cancel))

    def download_table(self):
        from ui.databricks_window import DatabricksWindow
        win=tk.Toplevel(self.root)
        view=DatabricksWindow(win,self.username,self.root,lambda:None)
        if self.table.get():
            view.fields['table'].set(self.table.get())
            view.target.set(self.table.get())

    def start(self,operation):
        if self.busy: return
        self.busy=True
        for widget in self.buttons+self.inputs: widget.configure(state='disabled')
        self.status.set(tr('Connecting to Databricks… Browser sign-in may be required.'))
        def worker():
            try:self.events.put((True,operation()))
            except Exception as error:self.events.put((False,str(error)))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        if self.closed:return
        try:ok,value=self.events.get_nowait()
        except queue.Empty:pass
        else:
            self.busy=False
            for widget in self.buttons:widget.configure(state='normal')
            for widget in self.inputs:widget.configure(state='normal' if widget is self.replace_box else 'readonly')
            self.status.set(tr('Done.')+(f' ({value})' if isinstance(value,int) else '') if ok else value)
        self.poll_id=self.root.after(100,self.poll)

    def close(self):
        self.closed=True
        self.cancel.set()
        self.root.after_cancel(self.poll_id)
        self.root.destroy()
        self.parent.deiconify()
