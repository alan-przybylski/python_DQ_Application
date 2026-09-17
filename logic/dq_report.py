"""Localized presentation for historical quality results."""

from datetime import date, datetime

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter
from matplotlib.dates import AutoDateLocator, ConciseDateFormatter

from config.i18n import tr
from database.connection import get_connection


def get_data_from_dq_results():
    connection = get_connection()
    try:
        rows = connection.execute("""
            SELECT rule_id,id,DATE(timestamp),
                   ROUND(100.0*passed_count/NULLIF(passed_count+failed_count,0),2)
            FROM dq_results ORDER BY rule_id,timestamp,id
        """).fetchall()
        return [
            (rule_id, number, date.fromisoformat(day), percent)
            for rule_id, number, day, percent in rows
        ]
    finally:
        connection.close()



def result_descriptions():
    connection = get_connection()
    try:
        return dict(connection.execute("""
            SELECT d.id, COALESCE(
                (SELECT h.description FROM dq_rules_history h
                 WHERE h.rule_id=d.rule_id AND h.version=d.rule_version
                 ORDER BY h.history_id DESC LIMIT 1),
                r.description, '')
            FROM dq_results d JOIN dq_rules r ON r.id=d.rule_id
        """).fetchall())
    finally:
        connection.close()


def label_positions(values):
    """Spread endpoint labels in axes coordinates without moving actual data."""
    if not values:
        return []
    gap = min(0.12, 0.84 / max(1, len(values)-1))
    positions = []
    for value in values:
        position = max(0.08, min(0.92, (value+3)/111))
        positions.append(max(position, positions[-1]+gap) if positions else position)
    overflow = max(0, positions[-1]-0.92)
    return [position-overflow for position in positions]


class ChartHover:
    def __init__(self, canvas, series):
        self.canvas, self.series = canvas, series
        self.popup = None
        self.text = ""
        self.motion_id = canvas.mpl_connect("motion_notify_event", self.on_motion)
        self.leave_id = canvas.mpl_connect("figure_leave_event", self.hide)
        canvas.get_tk_widget().bind("<Destroy>", self.dispose, add="+")

    def matching_points(self, event):
        if event.inaxes is None or event.x is None or event.y is None:
            return []
        matches = []
        for line, records in self.series:
            if line.axes != event.inaxes:
                continue
            pixels = line.axes.transData.transform(line.get_xydata())
            for (x, y), record in zip(pixels, records):
                distance = (x-event.x)**2 + (y-event.y)**2
                if distance <= 10**2:
                    matches.append((distance, record))
        return [record for _, record in sorted(matches, key=lambda item: item[0])]

    def on_motion(self, event):
        import tkinter as tk

        records = self.matching_points(event)
        if not records:
            self.hide()
            return
        blocks = []
        for record in records:
            description = record["description"] or "—"
            blocks.append(
                f"{tr('Rule')} #{record['rule_id']} · KPI: {record['percent']:.2f}%\n"
                f"{tr('Description')}: {description}\n"
                f"{tr('Date')}: {record['day']}"
            )
        text = "\n\n".join(blocks)
        widget = self.canvas.get_tk_widget()
        if self.popup is None:
            self.popup = tk.Toplevel(widget)
            self.popup.overrideredirect(True)
            self.popup.attributes("-topmost", True)
            self.label = tk.Label(self.popup, justify="left", anchor="w",
                                  background="#12243A", foreground="#FFFFFF",
                                  font=("Segoe UI", 10), padx=14, pady=10, wraplength=470)
            self.label.pack()
        if text != self.text:
            self.label.configure(text=text)
            self.text = text
        self.popup.update_idletasks()
        x = widget.winfo_pointerx()+18
        y = widget.winfo_pointery()+18
        x = max(0, min(x, widget.winfo_screenwidth()-self.popup.winfo_reqwidth()-12))
        y = max(0, min(y, widget.winfo_screenheight()-self.popup.winfo_reqheight()-12))
        self.popup.geometry(f"+{x}+{y}")

    def hide(self, event=None):
        if self.popup is not None:
            self.popup.destroy()
            self.popup = None
        self.text = ""

    def dispose(self, event=None):
        self.hide()
        self.canvas.mpl_disconnect(self.motion_id)
        self.canvas.mpl_disconnect(self.leave_id)


def draw_chart(frame, data):
    figure = Figure(figsize=(8, 2.4), dpi=100, facecolor="#FFFFFF")
    axis = figure.add_subplot(111)
    axis.set_facecolor("#FFFFFF")
    palette = ["#146C72", "#6366F1", "#C57B08", "#DC5967", "#3192C1"]
    descriptions = result_descriptions() if data else {}
    grouped = {}
    for rule_id, number, day, percent in data:
        if percent is not None:
            grouped.setdefault(rule_id, []).append({
                "rule_id": rule_id, "day": str(day), "percent": float(percent),
                "description": descriptions.get(number, ""),
            })
    series, endpoints = [], []
    for index, (rule_id, records) in enumerate(grouped.items()):
        color = palette[index % len(palette)]
        dates = [datetime.fromisoformat(record["day"]) for record in records]
        values = [record["percent"] for record in records]
        line, = axis.plot(dates, values, marker="o", markersize=6,
                          markeredgecolor="white", markeredgewidth=0.8,
                          linewidth=2, color=color)
        series.append((line, records))
        endpoints.append((values[-1], rule_id, dates[-1], color))
    if grouped:
        locator = AutoDateLocator(minticks=3, maxticks=5)
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(ConciseDateFormatter(locator))
        axis.tick_params(axis="x", labelsize=8)
        ordered = sorted(endpoints)
        for (value, rule_id, day, color), y in zip(ordered, label_positions([p[0] for p in ordered])):
            axis.annotate(f"{tr('Rule')} #{rule_id} · {value:.1f}%",
                          xy=(day, value), xycoords="data", xytext=(1.02, y),
                          textcoords="axes fraction", ha="left", va="center",
                          fontsize=9, fontweight="bold", color=color,
                          bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor=color, alpha=0.95),
                          arrowprops=dict(arrowstyle="-", color=color, linewidth=1),
                          annotation_clip=False)
    else:
        axis.text(0.5, 0.5, tr("No results yet"), ha="center", va="center",
                  transform=axis.transAxes, color="#526581")
        axis.set_xticks([])
    axis.set_ylim(-3, 108)
    axis.set_yticks([0, 25, 50, 75, 100])
    axis.yaxis.set_major_formatter(PercentFormatter())
    axis.tick_params(axis="y", labelsize=8, colors="#526581")
    axis.grid(axis="y", alpha=0.18)
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.spines["bottom"].set_color("#DDE5EF")
    figure.subplots_adjust(left=0.065, right=0.78, top=0.94, bottom=0.2)
    canvas = FigureCanvasTkAgg(figure, master=frame)
    canvas.dq_hover = ChartHover(canvas, series)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True)
    return canvas
