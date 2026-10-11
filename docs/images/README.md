# Presentation assets

The main README uses a small SVG header and an animated walkthrough assembled
from actual browser screenshots. All captured data is synthetic.

| Asset | Source |
|---|---|
| `brand/header.svg` | Editable vector artwork; demo counts describe the seeded dataset |
| `web/overview.png` | Public Streamlit demo, Overview |
| `web/data.png` | Public demo, customers dataset with deliberate issues |
| `web/rules.png` | Public demo, saved SQL rule library |
| `web/report-dirty.png` | Original customers run: 40 passed, 8 failed checks |
| `web/report-clean.png` | After applying the clean sample: 48 passed, 0 failed checks |
| `web/workflow.gif` | Four original browser captures with a caption strip |

Captured from https://alan-dq-studio.streamlit.app/ on 11 October 2026 in a
separate synthetic session. Each report refers to a real execution of the demo's
shared DQ engine. One record can fail multiple checks.

To rebuild the animation after replacing the four same-sized source captures:

```powershell
uv run --frozen python -m scripts.build_portfolio_gif
```

The root-level PNGs and `walkthrough.gif` are earlier desktop captures. The web
walkthrough is the current README showcase. A static final report is linked next
to the GIF for readers who prefer a still image.
