# QA Pulse — User Guide

**Version 1.0** | Apache License 2.0

This guide walks you through QA Pulse: how to run it, import test reports, use the dashboard, filters, multi-region/multi-device views, AI features, and sharing options.

---

## Table of Contents

1. [Getting Started](#1-getting-started)
2. [Navigation Overview](#2-navigation-overview)
3. [Global Filters](#3-global-filters)
4. [Importing Test Reports](#4-importing-test-reports)
5. [Dashboard](#5-dashboard)
6. [Run History](#6-run-history)
7. [Trends](#7-trends)
8. [Regions & Devices](#8-regions--devices)
9. [Compare Runs](#9-compare-runs)
10. [AI Triage & AI Insights](#10-ai-triage--ai-insights)
11. [Consolidated Batches](#11-consolidated-batches)
12. [Data Store](#12-data-store)
13. [API Integration (CI/CD)](#13-api-integration-cicd)
14. [Backup & Reset](#14-backup--reset)

---

## 1. Getting Started

### Requirements

- **Python 3.6 or newer**
- No pip installs
- No database setup
- All data stays local on your machine

### Start the Server

```bash
python3 server.py
```

The server starts on **port 7337**. Open your browser to:

```
http://localhost:7337
```

You will see the QA Pulse dashboard. The sidebar shows "Connected · localhost:7337" when the server is running.

---

## 2. Navigation Overview

The **sidebar** organizes all sections:

| Section | Purpose |
|--------|---------|
| **Overview** | |
| Dashboard | Main overview: KPIs, trends, test distribution, region/device health |
| Run History | Full list of all imported runs with search, filters, delete |
| Trends | Time-series charts: pass rate, volume, region/device breakdowns |
| **Multi-Dimension** | |
| Regions | Region heatmap, drill-down, region × device matrix |
| Devices | Device groups (Desktop, Mobile, Tablet), pass rate by device type |
| Compare Runs | Side-by-side comparison of up to 4 runs |
| **AI** | |
| AI Triage | Chat with AI about failures, trends, regions, devices |
| AI Insights | One-click AI-generated quality report |
| **Setup** | |
| Import Reports | Upload single files, multiple files, or Allure ZIP |
| **Share** | |
| Consolidated | Batches grouped by build, export as HTML or Markdown |
| Data Store | View JSON structure, size, backup guidance, reset option |

---

## 3. Global Filters

The **filter bar** (below the top bar) applies to the entire dashboard:

| Filter | Description |
|--------|-------------|
| **Region** | UK, DE, US East, etc. — or "All regions" |
| **Device** | Desktop Chrome, iPhone Safari, etc. — or "All devices" |
| **Env** | QA, Staging, Prod, Dev — or "All envs" |
| **Days** | Last 7, 30, 90 days, or last year |

**Behavior:** When you change a filter, all views (Dashboard, Trends, Regions, Devices, Run History, Test Distribution) update to show only runs matching that filter. For example, selecting **UK** + **Chrome** shows data only for UK Chrome runs.

The filter summary shows the active selection (e.g., "UK · Desktop Chrome · All envs · Last 30d").

---

## 4. Importing Test Reports

Go to **Import Reports** in the sidebar. There are **two modes**:

### Mode 1: Single / Multiple Files

Use for JUnit XML, Allure XML, Cucumber JSON, Playwright JSON, Mocha JSON, or ExtentReports HTML.

**Step 1 — Select files**

- Drag and drop files onto the upload zone, or click to browse
- Multiple files supported (.xml, .json, .html)

**Step 2 — Tag your run**

- **Region** (required) — e.g. UK, US East, EU West
- **Device** (required) — e.g. Desktop Chrome, iPhone Safari
- **Optional:** Run name, Environment, Branch, Build ID, OS, Browser

Region and device drive the multi-region and multi-device views.

**Step 3 — Confirm & upload**

- Review the summary and click **Upload all files**

### Mode 2: Allure JSON Folder / ZIP

Use for Allure `allure-results/` folders packaged as a ZIP.

**Supported ZIP structures:**

| Structure | Description |
|-----------|-------------|
| **Single folder** | `allure-results/` with `*.json` files → one run |
| **Multi-folder** | Sub-folders like `UK_desktop-chrome/`, `DE_android-chrome/` → one run per folder; region/device auto-detected from folder names |
| **Flat ZIP** | Direct `*.json` files → one run |

**Tag form:** For single-folder ZIPs, set Region and Device. For multi-folder ZIPs, QA Pulse infers them from folder names (e.g. `UK_desktop-chrome` → UK, Desktop Chrome).

---

## 5. Dashboard

The Dashboard is the main overview.

### Stats Row

- **Total runs** — Count of runs (respects filters)
- **Avg pass rate** — Average pass rate %
- **Total failures** — Total failed tests
- **Total tests run** — Total test count

### Pass Rate Trend

Line chart of daily pass rate over time (filtered by your selection).

### Test Distribution

- **Donut chart** — Passed, Failed, Skipped counts
- **Progress bar** — Pass rate %
- **Scope label** — "All runs" or filtered view (e.g. "UK · Desktop Chrome")

Distribution is aggregate across all filtered runs, not just the latest run.

### Region Health

Bar chart of pass rate by region (top 6).

### Device Health

Bar chart of pass rate by device (top 6), with Desktop/Mobile icons.

### Recent Runs

Table of the 8 most recent runs: Run name, Test, Suite, Region, Device, Pass %, Tests, Date. Click **View** to see details.

### Top Failing Tests

Table of tests that fail most often, with suite and region.

### Flaky Tests

Table of tests with multiple retries or inconsistent outcomes.

---

## 6. Run History

**Run History** lists all runs (filtered by region/device/env/days).

### Features

- **Search** — Filter by run name, test, suite, etc.
- **Columns:** Run name, Test, Suite, Region, Device, Env, Pass %, Tests, Failed, Duration, Date
- **View** — Opens run detail modal
- **Delete** — Removes run from the dashboard (with confirmation)

---

## 7. Trends

**Trends** provides time-series analytics:

- **Pass rate over time** — Line chart
- **Tests per day** — Volume chart
- **Pass rate by region** — Horizontal bar chart
- **Pass rate by device** — Horizontal bar chart
- **Avg duration trend (ms)** — Average test duration over time

All charts respect the global filters.

---

## 8. Regions & Devices

### Regions

- **Heatmap** — Click a region to drill down
- **Region detail** — Pass rate trend and top failures for that region
- **Region × Device matrix** — Table of pass rates per region/device combination

### Devices

- **Grouped view:** Desktop, Mobile, Tablet/API
- **Pass rate by device type** — Chart
- **Failures per device** — Chart

---

## 9. Compare Runs

**Compare Runs** lets you compare up to 4 runs side by side.

1. Select runs from the grid (up to 4)
2. Click **Compare →**
3. Review the comparison table and pass rate chart

---

## 10. AI Triage & AI Insights

### AI Triage (Chat)

- Ask questions about failures, trends, regions, and devices
- Suggested prompts: Region failures, Worst device, Flaky analysis, Pass rate trend, Error patterns
- Context is sent from your local data (region/device-aware)

### AI Insights

- Click **Generate insights** for an AI report
- Covers: regional disparity, device coverage, trend analysis, and other quality aspects
- Each insight includes severity and suggested action

---

## 11. Consolidated Batches

**Consolidated** groups runs by build into a single view.

### Viewing Batches

- Batches appear when you import runs with the same **Build ID**, or when you create a batch manually
- Each row: Batch name, Test summary, Suite, Run count, Regions, Devices, Pass %, Failed, Date
- **View** — Opens batch detail

### Batch Detail

- Run count, total tests, pass rate, failures
- Breakdown by region (runs, avg pass rate, total failed)
- Breakdown by device
- Runs table with Search, **Raw** (flat list), **Matrix** (region × device) views
- **Export** — HTML or Markdown

### Creating a Batch Manually

1. Click **＋ New batch**
2. Select a Build ID (from runs already imported)
3. Optionally add a batch name
4. Click **Create batch**

### Deleting a Batch

- Click **✕** on a batch row; confirm
- Only the batch grouping is removed; individual runs remain

---

## 12. Data Store

**Data Store** shows where your data lives:

- **Storage:** Plain JSON — editable in any text editor
- **Paths:** `data/runs.json`, `data/tests/<run-id>.json`
- **Stats:** Run count, test files count, total size

### Reset Dashboard

- **Reset dashboard** — Clears all runs and test files (with confirmation)
- Use when you want a clean slate

---

## 13. API Integration (CI/CD)

Use the REST API to import reports from Jenkins, GitHub Actions, GitLab CI, or any build system.

### Upload Endpoint

```
POST /api/upload
Content-Type: multipart/form-data
```

**Form fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `file` | Yes | Report file (.xml, .json, .html) |
| `region` | Yes | e.g. eu-west, UK, us-east |
| `device` | Yes | e.g. desktop-chrome, iphone-safari |
| `env` | No | qa, staging, prod, dev |
| `branch` | No | e.g. main |
| `build_id` | No | e.g. build-1234 |
| `run_name` | No | e.g. Sprint 42 Regression |

### Example (curl)

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

### ZIP Upload (multi-region)

```
POST /api/upload-zip
Content-Type: multipart/form-data
```

- Send a ZIP file containing Allure `allure-results/` or multi-folder structure
- Same metadata fields as single-file upload

---

## 14. Backup & Reset

### Backup

Copy the `data/` folder:

```bash
cp -r data/ data_backup/
```

### Reset (command line)

```bash
rm data/runs.json data/tests/*
```

### Reset (UI)

- Go to **Data Store**
- Click **Reset dashboard** and confirm

---

## Quick Reference

| Action | Location |
|--------|----------|
| Import reports | Sidebar → Import Reports |
| Filter by region/device | Global filter bar |
| View run details | Run History → View, or Dashboard → Recent runs → View |
| Compare runs | Compare Runs → Select runs → Compare → |
| AI chat | AI Triage |
| AI quality report | AI Insights → Generate insights |
| Create batch | Consolidated → ＋ New batch |
| Export batch | Consolidated → View batch → Export |
| Reset all data | Data Store → Reset dashboard |

---

*QA Pulse v1.0 — Licensed under Apache License 2.0*
