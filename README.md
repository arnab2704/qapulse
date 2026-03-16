# QA Pulse

**A local, zero-setup test results dashboard for QA teams.**

QA Pulse runs entirely on your machine. Upload test reports from JUnit, Allure, Playwright, and more — see pass rates, trends, region/device breakdowns, and AI-powered insights in seconds.

---

## Version & License

- **Version:** 1.0 (stable release)
- **License:** [Apache License 2.0](LICENSE) — free to use, modify, and distribute under the terms of the license.

---

## Quick Start

1. **Run the server**
   ```bash
   python3 server.py
   ```

2. **Open in your browser**
   ```
   http://localhost:7337
   ```

**Requirements:** Python 3.6 or newer. No pip installs. No database setup.

---

## What QA Pulse Does

| For | You Get |
|-----|---------|
| **Developers & QA** | Upload test reports and see pass rates, trends, and failures at a glance |
| **DevOps / CI** | Import results via API; integrate with Jenkins, GitHub Actions, GitLab CI |
| **Everyone** | Plain JSON storage — open `data/runs.json` in any text editor to view or edit your data |

---

## Where Your Data Lives

```
data/
  runs.json          ← Run metadata (human-readable, editable)
  tests/
    <run-id>.json    ← Test cases per run (one file per run)
```

**Backup:** `cp -r data/ data_backup/`  
**Reset:** `rm data/runs.json data/tests/*` (or use the Reset button in the app)

---

## Supported Report Formats

QA Pulse auto-detects these formats:

| Format | File type |
|--------|-----------|
| JUnit XML | `.xml` with `<testsuite>` root |
| Allure XML | `.xml` with `<test-case>` root |
| Cucumber JSON | `.json` with `elements` array |
| Playwright JSON | `.json` with `suites` and `specs` |
| Mocha JSON | `.json` with `passes` / `failures` |
| ExtentReports HTML | `.html` |

Upload via the web UI or use the API (see below).

---

## Importing via API (CI/CD)

Example for Jenkins, GitHub Actions, GitLab CI, or any build system:

```bash
curl -X POST http://localhost:7337/api/upload \
  -F "file=@target/surefire-reports/TEST-Suite.xml" \
  -F "region=eu-west" \
  -F "device=desktop-chrome" \
  -F "env=staging" \
  -F "branch=main" \
  -F "build_id=build-1234" \
  -F "run_name=Sprint 42 Regression"
```

Optional fields: `region`, `device`, `env`, `branch`, `build_id`, `run_name`.

---

## Dashboard Features

- **Dashboard** — KPIs, trend chart, test distribution, region/device health, recent runs, top failures, flaky tests
- **Run History** — Full history with search, filters, and delete
- **Trends** — Daily pass rate, volume, region and device breakdowns, duration
- **Regions** — Heatmap, region × device matrix, drill-down
- **Devices** — Grouped by Desktop, Mobile, Tablet
- **Compare** — Pick up to 4 runs and compare side-by-side
- **Consolidated Batches** — Group runs by build, export as HTML or Markdown
- **AI Triage** — Chat (region/device-aware context)
- **AI Insights** — One-click quality analysis
- **Data Store** — View JSON structure, size, and backup guidance

---

## Contributing & Support

QA Pulse is open source under Apache License 2.0. For bug reports, feature requests, or contributions, please open an issue or pull request in the project repository.

---

*QA Pulse v1.0 — Licensed under Apache License 2.0*
