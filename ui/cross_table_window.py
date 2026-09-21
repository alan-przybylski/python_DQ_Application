"""Named reference datasets and a guided EXISTS rule builder."""
import tkinter as tk
from tkinter import ttk, messagebox
from config.i18n import tr
from logic.datasets import list_tables, table_columns, quote
from logic.databricks_profiles import load_profiles
from logic.references import references, save_reference, create_cross_rule
from integrations.cross_table import compile_check
from ui.common import header, footer, error_box
from ui.utils import place_window


class CrossTableWindow:
    def __init__(self,root,username,on_saved):
        self.root,self.username,self.on_saved=root,username,on_saved
        place_window(root,1050,800)
        root.resizable(True,True)
        root.title(tr('Cross-table checks'))
        header(root,'Cross-table checks',username)
        footer(root,root.destroy)
        tabs=ttk.Notebook(root)
        tabs.pack(fill='both',expand=True,padx=20,pady=8)
        registry=ttk.Frame(tabs,padding=12)
        builder=ttk.Frame(tabs,padding=12)
        tabs.add(registry,text=tr('Reference datasets'))
        tabs.add(builder,text=tr('Build cross-table rule'))
        self.tables=list_tables()
        self.profiles=load_profiles()['profiles']
        self.ref_fields={}
        choices={'local_table':self.tables,'profile':['']+list(self.profiles)}
        for row,(key,label) in enumerate([('alias','Reference alias'),('local_table','Local reference table'),('profile','Connection profile'),('catalog','Source catalog'),('schema_name','Source schema'),('table_name','Source table / view')]):
            var=tk.StringVar(root)
            self.ref_fields[key]=var
            ttk.Label(registry,text=tr(label)).grid(row=row,column=0,sticky='w',pady=5)
            widget=ttk.Combobox(registry,textvariable=var,values=choices[key],state='readonly') if key in choices else ttk.Entry(registry,textvariable=var)
            widget.grid(row=row,column=1,sticky='ew',pady=5)
        registry.columnconfigure(1,weight=1)
        ttk.Label(registry,text=tr('Register a local copy. Remote fields are optional; fill all of them for Databricks. Changes require republishing cloud rules.'),wraplength=850).grid(row=6,column=0,columnspan=2,pady=8,sticky='w')
        ttk.Button(registry,text=tr('Save reference'),command=self.save_reference).grid(row=7,column=1,sticky='e')
        self.ref_list=ttk.Treeview(registry,columns=('local','remote'),show='tree headings',height=6)
        self.ref_list.heading('#0',text=tr('Reference alias'))
        self.ref_list.heading('local',text=tr('Local'))
        self.ref_list.heading('remote',text='Databricks')
        self.ref_list.grid(row=8,column=0,columnspan=2,sticky='nsew',pady=10)
        self.ref_list.bind('<<TreeviewSelect>>',self.load_reference)
        self.vars={}
        for row,(key,label,values,default) in enumerate([
            ('description','Description',None,''),('table','Table',self.tables,self.tables[0] if self.tables else ''),
            ('reference','Reference alias',[] ,''),('key','Record key',[],''),
            ('mode','Match requirement',[tr('Matching record must exist'),tr('Matching record must not exist')],tr('Matching record must exist')),
            ('nulls','Missing values',[tr('Fail missing values'),tr('Skip missing values')],tr('Fail missing values')),
            ('severity','Severity',['low','medium','high'],'high'),
            ('message','Message',None,'Invalid reference match'),
            ('active_column','Active reference column',[],''),
        ]):
            var=tk.StringVar(root,value=default)
            self.vars[key]=var
            ttk.Label(builder,text=tr(label)).grid(row=row,column=0,sticky='w',pady=3)
            widget=ttk.Entry(builder,textvariable=var) if values is None else ttk.Combobox(builder,textvariable=var,values=values,state='readonly')
            widget.grid(row=row,column=1,columnspan=3,sticky='ew',pady=3)
            if key=='reference': self.ref_picker=widget
            if key=='key': self.key_picker=widget
            if key=='active_column': self.active_picker=widget
            if key in ('table','reference'): widget.bind('<<ComboboxSelected>>',self.update_columns)
        self.normalize=tk.BooleanVar(root,value=False)
        ttk.Checkbutton(builder,text=tr('Ignore case and surrounding spaces'),variable=self.normalize).grid(row=9,column=0,columnspan=4,sticky='w',pady=4)
        self.source_column=tk.StringVar(root)
        self.reference_column=tk.StringVar(root)
        self.source_picker=ttk.Combobox(builder,textvariable=self.source_column,state='readonly')
        self.reference_picker=ttk.Combobox(builder,textvariable=self.reference_column,state='readonly')
        self.source_picker.grid(row=10,column=0,sticky='ew')
        ttk.Label(builder,text='→').grid(row=10,column=1)
        self.reference_picker.grid(row=10,column=2,sticky='ew')
        ttk.Button(builder,text=tr('Add column pair'),command=self.add_pair).grid(row=10,column=3)
        self.pairs=ttk.Treeview(builder,columns=('source','reference'),show='headings',height=3)
        self.pairs.heading('source',text=tr('Source column'))
        self.pairs.heading('reference',text=tr('Reference column'))
        self.pairs.grid(row=11,column=0,columnspan=3,sticky='ew',pady=4)
        ttk.Button(builder,text=tr('Remove pair'),command=lambda:self.pairs.delete(*self.pairs.selection())).grid(row=11,column=3)
        self.preview=tk.Text(builder,height=7,wrap='word',font=('Consolas',10),state='disabled')
        self.preview.grid(row=12,column=0,columnspan=4,sticky='nsew',pady=6)
        ttk.Button(builder,text=tr('Preview SQL'),command=self.show_sql).grid(row=13,column=0,sticky='w')
        ttk.Button(builder,text=tr('Create rule'),command=self.create).grid(row=13,column=3,sticky='e')
        builder.columnconfigure(2,weight=1)
        builder.rowconfigure(12,weight=1)
        self.refresh_references()
        self.update_columns()

    def refresh_references(self):
        self.refs={r['alias']:r for r in references()}
        self.ref_list.delete(*self.ref_list.get_children())
        for alias,r in self.refs.items():
            self.ref_list.insert('','end',iid=alias,text=alias,values=(r['local_table'],'.'.join([r['catalog'],r['schema_name'],r['table_name']]) if r['profile'] else '—'))
        self.ref_picker.configure(values=list(self.refs))
        if self.refs and not self.vars['reference'].get(): self.vars['reference'].set(next(iter(self.refs)))

    def load_reference(self,event=None):
        selected=self.ref_list.selection()
        if selected:
            for key,var in self.ref_fields.items(): var.set(self.refs[selected[0]][key])

    def save_reference(self):
        try:
            save_reference(self.username,**{k:v.get().strip() for k,v in self.ref_fields.items()})
            self.refresh_references()
            self.update_columns()
            messagebox.showinfo(tr('Success'),tr('Reference saved.'),parent=self.root)
        except Exception as error: error_box(error,self.root)

    def update_columns(self,event=None):
        try:
            columns=[c['name'] for c in table_columns(self.vars['table'].get())] if self.vars['table'].get() else []
            ref=self.refs.get(self.vars['reference'].get())
            other=[c['name'] for c in table_columns(ref['local_table'])] if ref else []
            self.key_picker.configure(values=columns)
            self.vars['key'].set('product_id' if 'product_id' in columns else 'id' if 'id' in columns else columns[0] if columns else '')
            self.source_picker.configure(values=columns)
            self.reference_picker.configure(values=other)
            self.active_picker.configure(values=['']+other)
            self.vars['active_column'].set('active_flag' if 'active_flag' in other else '')
            self.source_column.set(columns[0] if columns else '')
            self.reference_column.set(other[0] if other else '')
            self.pairs.delete(*self.pairs.get_children())
        except Exception as error: error_box(error,self.root)

    def add_pair(self):
        pair=(self.source_column.get(),self.reference_column.get())
        if all(pair) and pair not in [tuple(self.pairs.item(i,'values')) for i in self.pairs.get_children()]:
            self.pairs.insert('','end',values=pair)

    def spec(self):
        return dict(reference=self.vars['reference'].get(),key=self.vars['key'].get(),
                    pairs=[list(self.pairs.item(i,'values')) for i in self.pairs.get_children()],
                    mode='exists' if self.vars['mode'].get()==tr('Matching record must exist') else 'missing',
                    nulls='fail' if self.vars['nulls'].get()==tr('Fail missing values') else 'skip',
                    normalize=self.normalize.get(),active_column=self.vars['active_column'].get() or None)

    def show_sql(self):
        try:
            sql=compile_check(self.spec(),quote(self.vars['table'].get()))
            self.preview.configure(state='normal')
            self.preview.delete('1.0','end')
            self.preview.insert('1.0',sql)
            self.preview.configure(state='disabled')
        except Exception as error: error_box(error,self.root)

    def create(self):
        try:
            create_cross_rule(self.username,self.vars['description'].get(),self.vars['table'].get(),self.spec(),self.vars['message'].get(),self.vars['severity'].get())
            self.on_saved()
            messagebox.showinfo(tr('Success'),tr('Cross-table rule created. Run locally or map and publish it through Databricks sync.'),parent=self.root)
        except Exception as error: error_box(error,self.root)
