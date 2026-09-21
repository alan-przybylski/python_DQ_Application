"""The simple cloud workspace and compatible automatic result downloads."""
import queue
import threading
from config.i18n import tr
from logic.databricks_sync import mappings,synchronize
from ui.cloud_window import CloudWindow as DatabricksSyncWindow


def startup_sync(root,username,status):
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
