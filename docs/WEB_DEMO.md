# Web demo

**[Open the public demo](https://alan-dq-studio.streamlit.app/)** · [Project overview](../README.md)

The web interface lives in the same repository as desktop and uses its existing
SQLite DQ engine. It contains only synthetic data: 12 customers, 12 products and
four rules for each table. It requires no Databricks connection or login.

## Run locally (Windows)

From the repository directory:

```powershell
uv pip install --python .venv/Scripts/python.exe -r web_demo/requirements.txt
.venv/Scripts/python.exe -m streamlit run web_demo/app.py
```

Open `http://localhost:8501`. Alternatively, create a separate environment with
Python 3.13 or 3.14 and install `web_demo/requirements.txt` using pip.

## Recruiter walkthrough

1. Open Overview to see the two real baseline reports.
2. Select customers or products in the sidebar and open Data workspace.
3. Inspect the SQL in Rule library and run all four checks or one selected rule.
4. Open Quality report and investigate the failed records; export them as CSV.
5. Edit and save a value, or choose Apply clean sample + run checks.
6. Compare the resulting report with the baseline using the run selector.
7. Reset demo to restore the original data and reports.

SQL playground supports read-only draft previews against both datasets. Drafts
are not published or saved as rules. The initial rule library always contains
exactly eight rules. Preview limits: 500 rows, 10,000 SQL characters, 10 seconds.

## Publish on Streamlit Community Cloud

After pushing the completed demo to GitHub:

1. Sign in at https://share.streamlit.io/ and connect your GitHub account.
2. Choose **Create app** and the repository
   `alan-przybylski/python_DQ_Application`.
3. Select branch **main** for the public demo. Use **dev** only for a separate
   development preview.
4. Set the entrypoint to **web_demo/app.py**.
5. Choose Python **3.13** in Advanced settings (3.14 also works locally).
6. The published app uses **alan-dq-studio.streamlit.app**. Choose another
   available subdomain if deploying your own copy.
7. Click Deploy. No secrets, database upload or Databricks settings are required.
8. Make the app public in its sharing settings and test the link in incognito.

Community Cloud reads the lightweight `web_demo/requirements.txt` beside the
entrypoint before considering the desktop dependency files in the repository
root. It reads the theme from `.streamlit/config.toml`.

Deployment reference:
https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy

## Session isolation

Each browser session owns a temporary SQLite database outside the repository.
The app does not switch the global desktop database configuration, open private
`data/app.db`, read connection profiles or contact Databricks. Data edits and
reports are private to the current session and are not durable account storage.
Reloading/disconnecting may lose the session. Reset replaces only the caller's
synthetic database; other sessions and the desktop database remain untouched.

The editable datasets keep 12 fixed record IDs. Text values are limited to 500
characters. CSV exports escape spreadsheet formula prefixes.
