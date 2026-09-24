"""A compact work queue with linked evidence and a readable activity history."""

import json
import tkinter as tk
from tkinter import ttk

from config.i18n import tr
from logic.tickets import list_tickets, ticket_details, update_ticket, active_users, STATUS_LABELS
from ui.common import header, footer, table_view, error_box
from ui.rule_details import readonly_text
from ui.utils import place_window


class TicketsWindow:
    def __init__(self, root, username, role, dashboard_root, time_var, environment=None, profile=None):
        self.environment, self.profile = environment, profile
        self.root, self.username = root, username
        self.dashboard_root = dashboard_root
        place_window(root)
        root.title('DQ Studio / ' + tr('DQ tickets'))
        header(root, 'DQ tickets', username)
        if environment:
            tk.Label(root, text='Databricks' if environment == 'databricks' else 'Local / SQLite').pack(anchor='w', padx=20)
        footer(root, self.go_back, time_var)
        root.protocol('WM_DELETE_WINDOW', self.go_back)
        bar = tk.Frame(root)
        bar.pack(fill='x', padx=20, pady=12)
        self.scope = tk.StringVar(value=tr('Open tickets'))
        scope = ttk.Combobox(bar, textvariable=self.scope, state='readonly',
                             values=[tr('Open tickets'), tr('All tickets'), tr('Assigned to me'), tr('Overdue')], width=20)
        scope.pack(side='left')
        scope.bind('<<ComboboxSelected>>', lambda e: self.refresh())
        tk.Button(bar, text=tr('Open ticket'), command=self.open_ticket).pack(side='left', padx=8)
        tk.Button(bar, text=tr('Refresh'), command=self.refresh).pack(side='right')
        self.summary = tk.StringVar()
        tk.Label(root, textvariable=self.summary, anchor='w').pack(fill='x', padx=24)
        frame, self.tree = table_view(root, [('id', 'Ticket', 65), ('title', 'Description', 235),
            ('table', 'Table', 125), ('severity', 'Severity', 85), ('status', 'Status', 120),
            ('assignee', 'Assigned to', 130), ('due', 'Due date', 145), ('failed', 'Failed', 70)], 12)
        frame.pack(fill='both', expand=True, padx=24, pady=12)
        self.tree.tag_configure('overdue', foreground='#A32836')
        self.tree.bind('<Double-1>', self.open_ticket)
        self.tree.bind('<Return>', self.open_ticket)
        tk.Label(root, text=tr('Repeat failures update the open ticket. Deadlines never move automatically.'),
                 anchor='w', wraplength=1000).pack(fill='x', padx=24, pady=8)
        self.refresh()

    def go_back(self):
        self.root.destroy()
        self.dashboard_root.deiconify()

    def refresh(self):
        try:
            self.tree.delete(*self.tree.get_children())
            rows = list_tickets()
            from logic.workspaces import run_ids
            allowed = run_ids(self.environment, self.profile)
            if allowed is not None:
                rows = [row for row in rows if row['failure_run_id'] in allowed]
            for row in rows:
                scope = self.scope.get()
                if scope == tr('Open tickets') and row['status'] in ('closed', 'cancelled'):
                    continue
                if scope == tr('Assigned to me') and (row['assignee'] != self.username or row['status'] in ('closed', 'cancelled')):
                    continue
                if scope == tr('Overdue') and not row['overdue']:
                    continue
                self.tree.insert('', 'end', iid=str(row['id']), values=(row['id'], row['title'], row['table_name'],
                    row['severity'].title(), tr(STATUS_LABELS[row['status']]), row['assignee'], row['due_at'][:16], row['failed_count']),
                    tags=('overdue',) if row['overdue'] else ())
            self.summary.set(tr('{count} tickets · {overdue} overdue', count=len(self.tree.get_children()),
                                overdue=sum(r['overdue'] for r in rows)))
        except Exception as error:
            error_box(error, self.root)

    def open_ticket(self, event=None):
        selected = self.tree.selection()
        if not selected:
            return
        try:
            self.show_details(int(selected[0]))
        except Exception as error:
            error_box(error, self.root)

    def show_details(self, tid):
        ticket, history, errors = ticket_details(tid)
        win = tk.Toplevel(self.root)
        place_window(win)
        win.title(f'DQ Studio / #{tid}')
        header(win, 'DQ tickets', f'#{tid} · {ticket["severity"].title()}')
        footer(win, win.destroy)
        tk.Label(win, text=ticket['title'], font=('Segoe UI', 16, 'bold'), anchor='w',
                 wraplength=1000).pack(fill='x', padx=24, pady=10)
        tk.Label(win, text=f"{tr('Table')}: {ticket['table_name']} · {tr('Due date')}: {ticket['due_at']} · {tr('Status')}: {tr(STATUS_LABELS[ticket['status']])}",
                 anchor='w').pack(fill='x', padx=24)
        tabs = ttk.Notebook(win)
        tabs.pack(fill='both', expand=True, padx=24, pady=12)
        manage, evidence, activity = tk.Frame(tabs, padx=12, pady=8), tk.Frame(tabs), tk.Frame(tabs)
        for page, title in [(manage, 'Ownership'), (evidence, 'Failed records'), (activity, 'Activity')]:
            tabs.add(page, text=tr(title))
        metadata = f"{tr('Reporter')}: {ticket['reporter']}\n{tr('Imported by')}: {ticket['imported_by'] or '—'} · {ticket['source_file'] or '—'}\n{tr('First detected')}: {ticket['created_at']}\n{tr('Last detected')}: {ticket['last_seen']}"
        tk.Label(manage, text=metadata, justify='left', anchor='w').pack(fill='x', pady=8)
        tk.Label(manage, text=tr('Assigned to')).pack(anchor='w')
        assignee = tk.StringVar(value=ticket['assignee'])
        ttk.Combobox(manage, textvariable=assignee, values=sorted(set(active_users()+[ticket['assignee']])),
                     state='readonly', width=32).pack(anchor='w', pady=4)
        tk.Label(manage, text=tr('Status')).pack(anchor='w')
        statuses = [ticket['status']] if ticket['status'] in ('closed', 'cancelled') else ['new', 'in_progress', 'to_verify']
        status = tk.StringVar(value=tr(STATUS_LABELS[ticket['status']]))
        ttk.Combobox(manage, textvariable=status, state='readonly', width=32,
                     values=[tr(STATUS_LABELS[s]) for s in statuses]).pack(anchor='w', pady=4)
        tk.Label(manage, text=tr('Comment')).pack(anchor='w')
        comment = tk.Text(manage, height=3, wrap='word')
        comment.pack(fill='x', pady=4)
        tk.Label(manage, text=tr('Tickets close automatically after a successful DQ check with no errors.'),
                 wraplength=940, anchor='w').pack(fill='x', pady=4)

        def save():
            try:
                selected_status = next(s for s in statuses if tr(STATUS_LABELS[s]) == status.get())
                update_ticket(tid, self.username, assignee.get(), selected_status, comment.get('1.0', 'end-1c'))
                self.refresh()
                win.destroy()
            except Exception as error:
                error_box(error, win)

        tk.Button(manage, text=tr('Save changes'), command=save).pack(anchor='e', pady=4)
        tk.Label(evidence, text=tr('Latest failing check: up to 500 records. Closed tickets retain the last failure evidence.'),
                 wraplength=950).pack(anchor='w', padx=8, pady=8)
        frame, tree = table_view(evidence, [('id','Record',100), ('field','Field',150),
                                          ('value','Value',280), ('error','Error message',400)], 8)
        frame.pack(fill='both', expand=True)
        for row in errors:
            tree.insert('', 'end', values=[row[k] if row[k] is not None else 'NULL' for k in ('record_id','field_name','field_value','error_message')])
        lines = []
        for entry in history:
            detail = entry['detail']
            if entry['kind'] == 'updated':
                changes = json.loads(detail)
                detail = f"{changes['assignee']} · {tr(STATUS_LABELS[changes['status']])}"
            lines.append(f"{entry['created_at']} · {entry['actor']} · {tr(entry['kind'])}\n{detail}" +
                         (f" · {tr('Run')} #{entry['run_id']}" if entry['run_id'] else ''))
        readonly_text(activity, '\n\n'.join(lines))
        return win
