# QA Pulse — Local AI Test Dashboard

Zero-dependency local server. All data stored as **plain JSON files** — open and edit in any text editor.

## Quick Start

```bash
python3 server.py
# Open http://localhost:7337
```

Requires Python 3.6+. No pip installs. No database setup.

---

## Where your data lives

```
data/
  runs.json          ← all run metadata (human-readable, editable)
  tests/
    <run-id>.json    ← test cases per run (one file per run)
```

Open `data/runs.json` in VS Code, Notepad, or any text editor to see and edit your data directly.

**Backup:** `cp -r data/ data_backup/`  
**Reset:**  `rm data/runs.json data/tests/*`

---

## Supported formats (auto-detected)

| Format | File |
|---|---|
| JUnit XML | `.xml` with `<testsuite>` root |
| Allure XML | `.xml` with `<test-case>` root |
| Cucumber JSON | `.json` top-level array with `elements` |
| Playwright JSON | `.json` with `suites` + `specs` |
| Mocha JSON | `.json` with `passes` / `failures` |
| ExtentReports HTML | `.html` |

---

## Import via curl (CI/CD)

```bash
# Jenkins / GitHub Actions / GitLab CI
curl -X POST http://localhost:7337/api/upload \
  -F "file=@target/surefire-reports/TEST-Suite.xml" \
  -F "region=eu-west" \
  -F "device=desktop-chrome" \
  -F "env=staging" \
  -F "branch=main" \
  -F "build_id=build-1234" \
  -F "run_name=Sprint 42 Regression"
```

---

## Dashboard features

- **Dashboard** — KPIs, trend chart, region/device health, recent runs, top failures, flaky tests
- **Run History** — searchable full history with delete
- **Trends** — daily pass rate, volume, region bar, device bar, duration
- **Regions** — heatmap, region × device matrix, drill-down
- **Devices** — grouped by Desktop / Mobile / Tablet
- **Compare** — pick up to 4 runs side-by-side
- **AI Triage** — Claude-powered chat (region/device-aware context)
- **AI Insights** — one-click 6-point quality analysis
- **Data Store** — live view of your JSON files, structure, size, backup guide
