"""Streamlit entrypoint: streamlit run web_demo/app.py."""

from pathlib import Path
import sqlite3
import sys

# Community Cloud executes this entrypoint from its subdirectory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from config.i18n import AppError
from web_demo.service import DemoSession, TABLES

st.set_page_config(page_title="DQ Studio · Interactive demo", page_icon="🔎", layout="wide")
st.markdown("""<style>
.block-container {max-width: 1250px; padding-top: 2rem;}
.dq-hero {background:#12243a; color:white; padding:28px 32px; border-radius:16px; margin-bottom:24px;}
.dq-hero .label {color:#6fdae0; font-size:13px; letter-spacing:3px; font-weight:700;}
.dq-hero h1 {color:white; margin:8px 0; font-size:38px;}
.dq-hero p {color:#d3e0eb; margin:0; font-size:17px;}
[data-testid="stMetric"] {background:white; border:1px solid #dbe4ed; border-radius:12px; padding:16px;}
@media (max-width:1000px) {
  [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
  [data-testid="stColumn"] {min-width:180px !important; flex:1 1 180px !important;}
  [data-testid="stMetricValue"] {font-size:28px;}
  .dq-hero h1 {font-size:32px;}
}
</style>""", unsafe_allow_html=True)

if "demo" not in st.session_state:
    st.session_state.demo = DemoSession()
demo = st.session_state.demo


def frame(rows, columns=None):
    return pd.DataFrame(rows, columns=columns)


def csv_bytes(data):
    # Keep spreadsheet exports from interpreting visitor-entered text as formulas.
    safe = data.map(lambda value: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value)
    return safe.to_csv(index=False).encode("utf-8-sig")


def action(callback, message):
    try:
        result = callback()
    except (AppError, ValueError, sqlite3.Error) as error:
        st.error(str(error))
        return
    st.session_state.notice = message
    if isinstance(result, int):
        st.session_state.latest_run = result
    st.rerun()


with st.sidebar:
    st.markdown("## DQ / STUDIO")
    st.caption("Interactive portfolio · Alan Przybylski")
    page = st.radio("Explore", ["Overview", "Data workspace", "Rule library", "SQL playground", "Quality report", "About"], key="page")
    table = st.selectbox("Dataset", list(TABLES), key="table")
    st.divider()
    st.caption("Synthetic data · SQLite execution\n\nYour changes and reports belong to this browser session. Reloading may start a new session.")
    if st.button("Reset demo", width="stretch"):
        replacement = DemoSession()
        demo.close()
        for key in list(st.session_state):
            if key not in ("page", "table"):
                del st.session_state[key]
        st.session_state.demo = replacement
        st.session_state.notice = "Demo reset: original data and baseline reports restored."
        st.rerun()
    st.link_button("View source on GitHub", "https://github.com/alan-przybylski/python_DQ_Application", width="stretch")

notice = st.session_state.pop("notice", None)
if notice:
    st.success(notice)


def run_button(label="Run all 4 checks", rule_id=None, key=None):
    if st.button(label, type="primary", key=key):
        action(lambda: demo.run(table, rule_id), "Checks completed. Open Quality report to inspect this run.")


def overview():
    st.markdown("""<div class="dq-hero"><div class="label">DATA QUALITY · PYTHON · SQL</div>
    <h1>Make data quality visible.</h1>
    <p>Inspect the data. Understand the rules. Find the failures. Verify the repair.</p></div>""", unsafe_allow_html=True)
    latest = [demo.runs(name)[0] for name in TABLES]
    passed = sum(run["passed"] for run in latest)
    failed = sum(run["failed"] for run in latest)
    for column, label, value in zip(st.columns(4), ["Demo datasets", "SQL rules", "Latest check pass rate", "Failed checks"], [2, 8, f"{passed / (passed + failed):.1%}" if passed + failed else "—", failed]):
        column.metric(label, value)
    st.caption("Pass rate counts record–rule checks across the latest run of each dataset. One record can fail several rules.")
    st.subheader("Try a complete DQ workflow")
    for column, title, body in zip(st.columns(3), ["01 · Explore", "02 · Investigate", "03 · Verify"], ["Open Data workspace. Two datasets contain deliberate missing, duplicate and invalid values.", "Read the saved SQL in Rule library, run checks and inspect the failed records in Quality report.", "Edit a value or apply the clean sample, rerun checks and compare the new report with the original run."]):
        with column:
            with st.container(border=True):
                st.markdown(f"### {title}")
                st.write(body)
    st.subheader("Latest reports")
    st.dataframe(frame([{ "dataset": name, "run": run["id"], "completed rules": run["rules_completed"], "passed checks": run["passed"], "failed checks": run["failed"]} for name, run in zip(TABLES, latest)]), hide_index=True, width="stretch")
    st.info("Both baseline reports were executed by the DQ engine when your session started. Explore immediately or run another check.")
    run_button()


def data_workspace():
    st.title("Data workspace")
    st.write(f"**{table}** · 12 synthetic records · 4 SQL rules")
    st.caption("Edit values, save your changes, then rerun checks. Record IDs stay fixed so reports remain traceable.")
    data = frame(demo.query(f'SELECT * FROM "{table}" ORDER BY id'))
    with st.form(f"edit_{table}_{demo.revision}"):
        edited = st.data_editor(data, disabled=["id"], hide_index=True, num_rows="fixed", width="stretch", key=f"data_{table}_{demo.revision}")
        if st.form_submit_button("Save data changes"):
            records = edited.astype(object).where(pd.notna(edited), None).values.tolist()
            action(lambda: demo.save_rows(table, records), "Data saved. Run checks to measure the effect; earlier reports retain their original results.")
    left, right = st.columns(2)
    with left:
        run_button()
    with right:
        if st.button("Apply clean sample + run checks"):
            def clean_and_run():
                demo.clean(table)
                return demo.run(table)
            action(clean_and_run, "Clean sample applied and checked. Compare this run with the baseline in Quality report.")
    st.download_button("Download dataset CSV", csv_bytes(data), f"demo_{table}.csv", "text/csv")
    with st.expander("Declared column types"):
        st.dataframe(frame(demo.query(f'PRAGMA table_info("{table}")'))[["name", "type"]], hide_index=True)


def rule_library():
    st.title("Rule library")
    st.write(f"Four saved rules for **{table}**. Each SQL query produces a check for every record.")
    rules = demo.rules(table)
    st.dataframe(frame(rules)[["id", "description", "rule_type", "version", "status"]], hide_index=True, width="stretch")
    rule_id = st.selectbox("Inspect a rule", [rule["id"] for rule in rules], format_func=lambda rid: next(rule["description"] for rule in rules if rule["id"] == rid))
    rule = next(rule for rule in rules if rule["id"] == rule_id)
    st.write(rule["error_message"])
    st.code(rule["sql_query"], language="sql")
    st.caption("Output contract: id · tested field · dq_check, where 0 means PASS and 1 means FAIL.")
    run_button("Run selected rule", rule_id)
    with st.expander("All eight demo rules"):
        st.dataframe(frame(demo.query("SELECT target_table,description,rule_type FROM dq_rules ORDER BY id")), hide_index=True, width="stretch")


def sql_playground():
    st.title("SQL playground")
    st.write("Experiment with row-level DQ SQL against the two demo tables.")
    rules = demo.rules(table)
    index = st.selectbox("Start from a saved rule", range(len(rules)), format_func=lambda i: rules[i]["description"])
    sql = st.text_area("SQL", value=rules[index]["sql_query"], height=230, key=f"sql_{table}_{index}")
    st.caption("Use ordinary table names or {{SOURCE}}. Return id, a tested field as the second column and dq_check (0 or 1). Preview is read-only, limited to 500 rows and a 10-second query timeout.")
    if st.button("Preview SQL", type="primary"):
        try:
            result = demo.preview(sql, table)
        except (AppError, ValueError, sqlite3.Error) as error:
            st.error(str(error))
        else:
            st.success(f"{len(result)} records · {sum(row['dq_check'] == 1 for row in result)} failed checks")
            st.dataframe(frame(result), hide_index=True, width="stretch")
    st.info("Playground queries preview your draft. To create a historical report, run a saved rule from Rule library.")


def quality_report():
    st.title("Quality report")
    runs = demo.runs(table)
    chosen = st.session_state.get("latest_run")
    options = [run["id"] for run in runs]
    run_id = st.selectbox("Run", options, index=options.index(chosen) if chosen in options else 0, format_func=lambda rid: next(f"Run #{run['id']} · {run['started_at']} · {run['rules_completed']} rules" for run in runs if run["id"] == rid))
    run = next(run for run in runs if run["id"] == run_id)
    total = run["passed"] + run["failed"]
    for column, label, value in zip(st.columns(4), ["Run", "Pass rate", "Passed checks", "Failed checks"], [f"#{run_id}", f"{run['passed'] / total:.1%}" if total else "—", run["passed"], run["failed"]]):
        column.metric(label, value)
    st.caption(f"Execution status: {run['status']}. Each run is a separate snapshot; data edits do not rewrite it. Pass rate counts record–rule checks.")
    execution = demo.query("SELECT execution_errors FROM dq_runs WHERE id=?", (run_id,))[0]["execution_errors"]
    if execution != "[]":
        st.error(f"Some SQL rules could not execute: {execution}")
    report = frame(demo.report(run_id))
    st.subheader("Results by rule")
    st.dataframe(report, hide_index=True, width="stretch")
    if not report.empty:
        st.bar_chart(report.set_index("rule")[["passed", "failed"]], color=["#16838a", "#df695b"], horizontal=True)
    st.subheader("Failed records")
    failures = frame(demo.failures(run_id), ["rule", "record_id", "field_name", "field_value", "error_message"])
    if failures.empty and run["status"] == "completed":
        st.success("All executed checks passed for this run.")
    elif failures.empty:
        st.warning("There are no failed record results, but this run did not complete successfully.")
    else:
        st.dataframe(failures, hide_index=True, width="stretch")
    st.download_button("Download failed records CSV", csv_bytes(failures), f"{table}_run_{run_id}_failures.csv", "text/csv")
    st.subheader("Run history")
    st.caption("Compare runs with the same set of rules. A run with one rule measures only that rule.")
    st.dataframe(frame(runs), hide_index=True, width="stretch")


def about():
    st.title("About DQ Studio")
    st.write("A Python / SQL data quality project by **Alan Przybylski**.")
    st.markdown("""This interactive demo demonstrates:

- SQL rules for completeness, validity, range and uniqueness.
- Row-level evidence behind each failure.
- Separate run objects with immutable result history.
- Repairing data and verifying the next run.
- A shared Python DQ engine used by the desktop and web interfaces.

The full desktop application also includes CSV imports, Databricks workspaces,
rule publication, cloud result downloads, user management and DQ tickets.
This public demo executes against synthetic SQLite datasets. Live Databricks
connections and account administration are available in the desktop application.
""")
    st.info("The demo starts with 12 customers and 12 products, four rules per table and two baseline reports. Changes last for your current browser session. Reset demo restores the starting state.")


{"Overview": overview, "Data workspace": data_workspace, "Rule library": rule_library,
 "SQL playground": sql_playground, "Quality report": quality_report, "About": about}[page]()
