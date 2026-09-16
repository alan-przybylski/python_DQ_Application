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


def draw_chart(frame, data):
    figure = Figure(figsize=(8, 2.4), dpi=100, facecolor="#FFFFFF")
    axis = figure.add_subplot(111)
    axis.set_facecolor("#FFFFFF")
    palette = ["#146C72", "#6366F1", "#E39824", "#DC5967", "#3192C1"]
    grouped = {}
    for rule_id, number, day, percent in data:
        if percent is not None:
            grouped.setdefault(rule_id, []).append((str(day), percent))
    for index, (rule_id, points) in enumerate(grouped.items()):
        days, values = zip(*points)
        axis.plot(
            [datetime.fromisoformat(day) for day in days],
            values,
            marker="o",
            markersize=4,
            linewidth=2,
            color=palette[index % len(palette)],
            label=f"{tr('Rule')} {rule_id}",
        )
    if grouped:
        locator = AutoDateLocator(minticks=3, maxticks=5)
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(ConciseDateFormatter(locator))
        axis.tick_params(axis="x", labelsize=8)
        axis.legend(
            loc="lower left", fontsize=8, frameon=False, ncol=min(4, len(grouped))
        )
    else:
        axis.text(
            0.5,
            0.5,
            tr("No results yet"),
            ha="center",
            va="center",
            transform=axis.transAxes,
            color="#526581",
        )
        axis.set_xticks([])
    axis.set_ylim(-3, 105)
    axis.yaxis.set_major_formatter(PercentFormatter())
    axis.tick_params(axis="y", labelsize=8, colors="#526581")
    axis.grid(axis="y", alpha=0.18)
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.spines["bottom"].set_color("#DDE5EF")
    figure.subplots_adjust(left=0.065, right=0.98, top=0.94, bottom=0.2)
    canvas = FigureCanvasTkAgg(figure, master=frame)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True)
    return canvas
