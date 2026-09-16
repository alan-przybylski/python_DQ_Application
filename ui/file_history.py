from config.i18n import tr
from database.connection import get_connection
from ui.common import header, footer, table_view
from ui.utils import place_window


class FileHistory:
    def __init__(self, root, username, role, dashboard_root, time_var):
        self.root, self.dashboard_root = root, dashboard_root
        place_window(root)
        root.title("DQ Studio / " + tr("Import history"))
        header(root, "Import history", username)
        footer(root, self.go_back, time_var)
        root.protocol("WM_DELETE_WINDOW", self.go_back)
        frame, self.tree = table_view(
            root,
            [
                ("id", "Run", 60),
                ("table_name", "Table", 150),
                ("file_name", "File", 320),
                ("row_count", "Rows", 80),
                ("loaded_by", "Imported by", 150),
                ("loaded_at", "Date", 180),
            ],
            14,
        )
        frame.pack(fill="both", expand=True, padx=20, pady=16)
        self.import_data_load_log()

    def import_data_load_log(self):
        connection = get_connection()
        try:
            self.tree.delete(*self.tree.get_children())
            for row in connection.execute(
                "SELECT * FROM data_load_log ORDER BY id DESC"
            ):
                self.tree.insert("", "end", values=row)
        finally:
            connection.close()

    def on_close(self):
        self.go_back()

    def go_back(self):
        self.root.destroy()
        self.dashboard_root.deiconify()
