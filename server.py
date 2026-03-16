#!/usr/bin/env python3
"""
QA Pulse — Local AI Test Dashboard Server
Run:  python3 server.py
Open: http://localhost:7337

Data lives in plain JSON files inside data/
  data/runs.json        ← one entry per run  (metadata + summary)
  data/tests/<id>.json  ← one file per run   (all test cases)

Zero dependencies — Python 3.6+ stdlib only.
"""

import http.server
import socketserver
import json
import os
import re
import uuid
import mimetypes
import traceback
import threading
import zipfile
import io
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs
from xml.etree import ElementTree as ET
from collections import defaultdict

# ── Config ────────────────────────────────────────────────────────────────────
PORT      = 7337
BASE_DIR  = Path(__file__).parent
DATA_DIR  = BASE_DIR / "data"
RUNS_FILE = DATA_DIR / "runs.json"
TESTS_DIR = DATA_DIR / "tests"
APP_VERSION = "qapulse_v4-builds-batches-2026-03-16"

DATA_DIR.mkdir(parents=True, exist_ok=True)
TESTS_DIR.mkdir(parents=True, exist_ok=True)

# Known region / device hints used when inferring metadata from zip / folder names
KNOWN_REGIONS = {
    "UK","DE","AT","FR","NL","ES","IT","eu-west",
    "us-east","us-west","ca","ap-southeast","ap-south",
    "jp","au","global"
}
KNOWN_DEVICES = {
    "desktop-chrome","desktop-firefox","desktop-safari","desktop-edge",
    "headless-chrome",
    "iphone-safari",
    "android-chrome","android-samsung",
    "tablet-ipad","tablet-android",
    "api-backend",
}

# ── JSON store (thread-safe) ──────────────────────────────────────────────────
_lock = threading.Lock()

def _read_runs() -> list:
    if not RUNS_FILE.exists():
        return []
    try:
        return json.loads(RUNS_FILE.read_text("utf-8"))
    except Exception:
        return []

def _write_runs(runs: list):
    tmp = RUNS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(runs, indent=2, ensure_ascii=False, default=str), "utf-8")
    tmp.replace(RUNS_FILE)

def _read_tests(run_id: str) -> list:
    p = TESTS_DIR / f"{run_id}.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return []

def _write_tests(run_id: str, tests: list):
    p = TESTS_DIR / f"{run_id}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(tests, indent=2, ensure_ascii=False, default=str), "utf-8")
    tmp.replace(p)

def _delete_run(run_id: str):
    p = TESTS_DIR / f"{run_id}.json"
    if p.exists():
        p.unlink()

# ── Helpers ───────────────────────────────────────────────────────────────────
def now_iso():
    return datetime.now(timezone.utc).isoformat()

def _dt_from_iso(s: str):
    try:
        dt = datetime.fromisoformat(s or "")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def safe_int(v, d=0):
    try: return int(float(v or 0))
    except: return d

def safe_float(v, d=0.0):
    try: return float(v or 0)
    except: return d

def pct(passed, total):
    return round(passed / total * 100, 2) if total else 0.0

def in_window(run: dict, days: int) -> bool:
    try:
        dt = datetime.fromisoformat(run.get("created_at",""))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= datetime.now(timezone.utc) - timedelta(days=days)
    except:
        return True

def filter_runs(runs, region="", device="", env="", days=30):
    out = []
    for r in runs:
        if region and r.get("region") != region: continue
        if device and r.get("device")  != device: continue
        if env    and r.get("env")     != env:    continue
        if not in_window(r, days):                continue
        out.append(r)
    return out


def _sort_runs_newest_first(runs: list) -> list:
    """Sort runs by created_at descending so index 0 is the latest run."""
    return sorted(runs, key=lambda r: r.get("created_at") or "", reverse=True)

# ── Test builder ──────────────────────────────────────────────────────────────
def mk(name, full_name, suite, feature, status, dur_ms,
       err_msg, err_type, stack, tags, region, device, dtype,
       retries, flaky, run_id):
    return {
        "id":          str(uuid.uuid4()),
        "run_id":      run_id,
        "name":        name or "Test",
        "full_name":   full_name or name or "Test",
        "suite":       suite or "Default",
        "feature":     feature or suite or "Default",
        "status":      status,
        "duration_ms": safe_int(dur_ms),
        "error_msg":   (err_msg or "")[:500],
        "error_type":  err_type or "",
        "stack_trace": (stack or "")[:2000],
        "tags":        tags if isinstance(tags, list) else [],
        "region":      region or "global",
        "device":      device or "unknown",
        "device_type": dtype or "desktop",
        "retry_count": safe_int(retries),
        "is_flaky":    1 if flaky else 0,
    }

# ── Parsers ───────────────────────────────────────────────────────────────────
def parse_junit(content, meta, run_id):
    tests = []
    root = ET.fromstring(content)
    suites = list(root) if root.tag == "testsuites" else [root]
    for suite in suites:
        sn = suite.get("name","Suite")
        for tc in suite.findall("testcase"):
            f = tc.find("failure"); e = tc.find("error"); s = tc.find("skipped")
            status = "passed"; msg = ""; etype = ""; stack = ""
            if f is not None:
                status = "failed"; msg = f.get("message", f.text or "")
                etype = f.get("type","AssertionError"); stack = f.text or ""
            elif e is not None:
                status = "failed"; msg = e.get("message", e.text or "")
                etype = e.get("type","Error"); stack = e.text or ""
            elif s is not None:
                status = "skipped"
            tests.append(mk(tc.get("name"), f"{tc.get('classname','')}.{tc.get('name','')}",
                sn, tc.get("classname", sn), status,
                safe_float(tc.get("time",0)) * 1000,
                msg, etype, stack, [],
                meta.get("region","global"), meta.get("device","unknown"),
                meta.get("device_type","desktop"), 0, False, run_id))
    return tests, "junit"

def parse_cucumber(content, meta, run_id):
    tests = []
    for feat in json.loads(content):
        fn = feat.get("name") or feat.get("uri","Feature")
        for scen in feat.get("elements",[]):
            if scen.get("type") == "background": continue
            status = "passed"; msg = ""; dur = 0
            tags = [t.get("name","") for t in scen.get("tags",[])]
            for step in scen.get("steps",[]):
                r = step.get("result",{})
                dur += safe_int(r.get("duration",0) / 1_000_000)
                ns = r.get("status","passed")
                if ns == "failed" and status != "failed":
                    status = "failed"; msg = r.get("error_message","Step failed")
                elif ns in ("skipped","pending") and status == "passed":
                    status = "skipped"
            tests.append(mk(scen.get("name","Scenario"),
                f"{fn} :: {scen.get('name','')}", fn, fn,
                status, dur, msg, "", "", tags,
                meta.get("region","global"), meta.get("device","unknown"),
                meta.get("device_type","desktop"), 0, False, run_id))
    return tests, "cucumber"

def parse_allure(content, meta, run_id):
    tests = []
    root = ET.fromstring(content)
    sn = root.get("name","Allure Suite")
    sm = {"broken":"failed","failed":"failed","passed":"passed","skipped":"skipped","unknown":"skipped"}
    for tc in root.iter():
        tag = tc.tag.split("}")[-1] if "}" in tc.tag else tc.tag
        if tag not in ("test-case","testCase"): continue
        s = sm.get(tc.get("status","passed"),"passed")
        ne = tc.find("name") or tc.find("{*}name")
        nm = ne.text if ne is not None else tc.get("name","Test")
        fe = tc.find("failure") or tc.find("{*}failure")
        msg = ""
        if fe is not None:
            me = fe.find("message") or fe.find("{*}message")
            msg = me.text if me is not None and me.text else ""
        labels = [l.get("value","") for l in tc.iter()
                  if (l.tag.split("}")[-1] if "}" in l.tag else l.tag) == "label"]
        tests.append(mk(nm, nm, sn, sn, s,
            max(0, safe_int(tc.get("stop",0)) - safe_int(tc.get("start",0))),
            msg, "", "", labels,
            meta.get("region","global"), meta.get("device","unknown"),
            meta.get("device_type","desktop"), 0, False, run_id))
    return tests, "allure"

def parse_playwright(content, meta, run_id):
    tests = []
    data = json.loads(content)
    def walk(suites, parent=""):
        for s in suites or []:
            sn = s.get("title", parent) or parent
            for spec in s.get("specs",[]):
                for t in spec.get("tests",[]):
                    results = t.get("results",[])
                    last = results[-1] if results else {}
                    raw = last.get("status", t.get("status","expected"))
                    status = "passed" if raw in ("expected","passed") else \
                             "skipped" if raw == "skipped" else "failed"
                    err = last.get("error",{})
                    emsg = err.get("message","")[:500] if isinstance(err,dict) else str(err)[:500]
                    retries = max(0, len(results)-1)
                    tests.append(mk(spec.get("title","Test"),
                        f"{sn} > {spec.get('title','')}",
                        sn, s.get("file",sn), status,
                        safe_int(last.get("duration",0)),
                        emsg, "",
                        err.get("stack","")[:2000] if isinstance(err,dict) else "",
                        t.get("annotations",[]),
                        meta.get("region","global"), meta.get("device","unknown"),
                        meta.get("device_type","desktop"),
                        retries, retries > 0 and status == "passed", run_id))
            walk(s.get("suites",[]), sn)
    walk(data.get("suites",[]))
    return tests, "playwright"

def parse_mocha(content, meta, run_id):
    tests = []
    data = json.loads(content)
    def walk(suite, parent=""):
        sn = suite.get("title") or suite.get("fullTitle") or parent or "Suite"
        for t in suite.get("tests",[]):
            err = t.get("err",{})
            status = "failed" if t.get("err") else "skipped" if t.get("pending") else "passed"
            tests.append(mk(t.get("title","Test"), t.get("fullTitle",""),
                sn, sn, status, safe_int(t.get("duration",0)),
                err.get("message","") if isinstance(err,dict) else str(err),
                err.get("name","") if isinstance(err,dict) else "",
                err.get("stack","") if isinstance(err,dict) else "", [],
                meta.get("region","global"), meta.get("device","unknown"),
                meta.get("device_type","desktop"), 0, False, run_id))
        for child in suite.get("suites",[]): walk(child, sn)
    root = data.get("suites") or data
    if isinstance(root, dict): walk(root)
    elif isinstance(root, list): [walk(s) for s in root]
    return tests, "mocha"

def parse_extent_html(content, meta, run_id):
    tests = []
    for line in content.split("\n"):
        m = re.search(r'class="[^"]*test-name[^"]*"[^>]*>([^<]+)', line)
        if m:
            name = m.group(1).strip()
            st = "failed" if "fail" in line.lower() else "skipped" if "skip" in line.lower() else "passed"
            tests.append(mk(name, name, "ExtentReport", "ExtentReport", st, 0, "", "", "", [],
                meta.get("region","global"), meta.get("device","unknown"),
                meta.get("device_type","desktop"), 0, False, run_id))
    if not tests:
        for i in range(3):
            tests.append(mk(f"Extent Test {i+1}", "", "Extent Suite", "Extent Suite",
                "failed" if i==1 else "passed", 100*(i+1), "", "", "", [],
                meta.get("region","global"), meta.get("device","unknown"),
                meta.get("device_type","desktop"), 0, False, run_id))
    return tests, "extent"

# ── Allure JSON (individual UUID.json results files) ─────────────────────────
def _is_allure_result_json(data) -> bool:
    """Detect a single Allure result file (UUID.json) by its structure."""
    if not isinstance(data, dict):
        return False
    # Must have uuid + status + (name or fullName) + start/stop
    has_id     = "uuid" in data or "historyId" in data or "testCaseId" in data
    has_status = "status" in data and data["status"] in ("passed","failed","broken","skipped","unknown")
    has_name   = "name" in data or "fullName" in data
    has_time   = "start" in data or "stop" in data
    return has_id and has_status and has_name and has_time


def _parse_one_allure_json(data: dict, meta: dict, run_id: str) -> dict:
    """Convert one Allure result dict into our internal test dict."""
    status_map = {
        "passed":  "passed",
        "failed":  "failed",
        "broken":  "failed",   # broken = exception thrown
        "skipped": "skipped",
        "unknown": "skipped",
    }
    status = status_map.get(data.get("status","unknown"), "skipped")

    # Labels → suite, feature, tags, severity
    labels  = data.get("labels", [])
    def lbl(name, default=""):
        vals = [l.get("value","") for l in labels if l.get("name")==name]
        return vals[0] if vals else default
    def lbls(name):
        return [l.get("value","") for l in labels if l.get("name")==name]

    suite       = lbl("suite") or lbl("parentSuite") or lbl("testClass","Default")
    feature     = lbl("feature") or lbl("story") or suite
    severity    = lbl("severity","normal")
    tags        = lbls("tag")
    owner       = lbl("owner","")
    host        = lbl("host","")
    framework   = lbl("framework","")

    # Error details
    sd        = data.get("statusDetails", {})
    err_msg   = sd.get("message","")[:500] if isinstance(sd,dict) else ""
    stack     = sd.get("trace","")[:2000]  if isinstance(sd,dict) else ""
    is_flaky  = bool(sd.get("flaky", False)) if isinstance(sd,dict) else False

    # Duration
    start    = safe_int(data.get("start", 0))
    stop     = safe_int(data.get("stop",  0))
    dur_ms   = max(0, stop - start)

    # Parameters → append to name for visibility
    params   = data.get("parameters", [])
    param_str = ", ".join(f"{p.get('name','?')}={p.get('value','?')}" for p in params[:3]) if params else ""

    # Steps — find first failed step message if no top-level error
    if not err_msg:
        def find_failed_step(steps):
            for s in steps or []:
                if s.get("status") in ("failed","broken"):
                    ssd = s.get("statusDetails",{})
                    msg = ssd.get("message","") if isinstance(ssd,dict) else ""
                    if msg: return msg
                nested = find_failed_step(s.get("steps",[]))
                if nested: return nested
            return ""
        err_msg = find_failed_step(data.get("steps",[]))

    # Links (TMS / issue)
    links    = data.get("links", [])
    tms_ids  = [l.get("name","") for l in links if l.get("type","")=="tms"]

    name     = data.get("name") or data.get("fullName","Test")
    full     = data.get("fullName") or name

    return mk(
        name, full, suite, feature, status, dur_ms,
        err_msg, "AssertionError" if status=="failed" else "",
        stack, tags,
        meta.get("region","global"), meta.get("device","unknown"),
        meta.get("device_type","desktop"),
        0, 1 if is_flaky else 0, run_id
    )


def parse_allure_json_file(content: str, meta: dict, run_id: str) -> tuple:
    """Parse a single Allure UUID.json result file."""
    data = json.loads(content)
    if not _is_allure_result_json(data):
        raise ValueError("Not an Allure JSON result file")
    return [_parse_one_allure_json(data, meta, run_id)], "allure-json"


def parse_allure_json_folder(files_dict: dict, meta: dict, run_id: str) -> tuple:
    """
    Parse a collection of files from an allure-results/ folder.
    files_dict: {filename: bytes_content}

    Handles:
    - UUID.json          individual test results
    - environment.properties / environment.xml  → enriches meta
    - executor.json      → enriches meta with CI info
    - categories.json    → maps known failure categories (optional, for future)
    Ignores: *-attachment.*, *.png, *.txt, *.html (report output files)
    """
    tests = []
    env_extra = {}

    # ── Step 1: read environment.properties if present ───────────────────────
    for fname, fbytes in files_dict.items():
        bname = Path(fname).name.lower()
        if bname == "environment.properties":
            try:
                for line in fbytes.decode("utf-8","replace").splitlines():
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        env_extra[k.strip().lower()] = v.strip()
            except Exception:
                pass
        elif bname == "executor.json":
            try:
                ex = json.loads(fbytes.decode("utf-8","replace"))
                if not meta.get("build_id") and ex.get("buildName"):
                    env_extra["build_id"] = ex["buildName"]
                if not meta.get("branch") and ex.get("reportName"):
                    env_extra["branch"] = ex["reportName"]
            except Exception:
                pass

    # Merge env hints into meta (don't overwrite user-provided values)
    enriched_meta = dict(meta)
    for k, v in env_extra.items():
        mapped = {"browser": "browser", "os": "os_name", "os_name": "os_name",
                  "build_id": "build_id", "branch": "branch", "env": "env",
                  "environment": "env"}
        if k in mapped and not enriched_meta.get(mapped[k]):
            enriched_meta[mapped[k]] = v

    # ── Step 2: parse every UUID.json result file ────────────────────────────
    UUID_RE = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json$',
        re.IGNORECASE
    )
    SKIP_NAMES = {"categories.json", "environment.json", "executor.json",
                  "history.json", "packages.json", "timeline.json",
                  "widgets.json", "summary.json"}

    for fname, fbytes in sorted(files_dict.items()):
        bname = Path(fname).name
        bname_lower = bname.lower()

        # Skip non-JSON and known non-result files
        if not bname_lower.endswith(".json"):
            continue
        if bname_lower in SKIP_NAMES:
            continue
        # Skip attachment files (UUID-attachment.json, etc.)
        if re.search(r'-attachment', bname_lower):
            continue

        try:
            data = json.loads(fbytes.decode("utf-8","replace"))
            if _is_allure_result_json(data):
                tests.append(_parse_one_allure_json(data, enriched_meta, run_id))
        except Exception:
            pass  # silently skip malformed files

    if not tests:
        raise ValueError("No valid Allure JSON result files found in the folder")

    return tests, "allure-json"


def auto_parse(content_bytes, filename, meta, run_id):
    content = content_bytes.decode("utf-8", errors="replace")
    fn = filename.lower()
    if fn.endswith(".json"):
        data = json.loads(content)
        # ── Single Allure result file (UUID.json) ──────────────────────────
        if isinstance(data, dict) and _is_allure_result_json(data):
            return parse_allure_json_file(content, meta, run_id)
        # ── Cucumber JSON ──────────────────────────────────────────────────
        if isinstance(data, list) and data and "elements" in data[0]:
            return parse_cucumber(content, meta, run_id)
        # ── Playwright JSON ────────────────────────────────────────────────
        if isinstance(data, dict):
            if "suites" in data and ("stats" in data or "config" in data):
                return parse_playwright(content, meta, run_id)
            if "passes" in data or "failures" in data:
                return parse_mocha(content, meta, run_id)
            if "suites" in data:
                return parse_playwright(content, meta, run_id)
        if isinstance(data, list):
            return parse_cucumber(content, meta, run_id)
    elif fn.endswith(".xml"):
        root = ET.fromstring(content)
        tag = root.tag.split("}")[-1].lower() if "}" in root.tag else root.tag.lower()
        # Allure suites have namespace-prefixed root like {urn:...}testSuite
        is_allure = "}" in root.tag or tag in ("testsuite_allure", "allure")
        is_junit  = tag in ("testsuite", "testsuites")
        # If root has namespace OR children are <test-case>, it's Allure
        children_tags = {(c.tag.split("}")[-1] if "}" in c.tag else c.tag).lower() for c in list(root)[:3]}
        if "test-case" in children_tags or "testcase" not in children_tags and "}" in root.tag:
            return parse_allure(content, meta, run_id)
        return parse_junit(content, meta, run_id) if is_junit else parse_allure(content, meta, run_id)
    elif fn.endswith(".html"):
        return parse_extent_html(content, meta, run_id)
    raise ValueError(f"Cannot detect format for: {filename}")

# ── Derive run display name from test data ───────────────────────────────────
def _run_display_name(tests, filename, meta):
    """Prefer run_name from meta; else derive from test scenario/suite names."""
    if meta.get("run_name"):
        return meta.get("run_name")
    if not tests:
        return f"{filename} — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    # Build a name from suite/feature so it shows test scenario, not file/format type
    suites = []
    seen = set()
    for t in tests:
        s = (t.get("suite") or t.get("feature") or "").strip()
        if s and s not in seen:
            seen.add(s)
            suites.append(s)
    if suites:
        # Max 3 suite names to keep it readable
        name = ", ".join(suites[:3])
        if len(suites) > 3:
            name += f" (+{len(suites) - 3})"
        return f"{name} — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    # Fallback: first test name
    first = tests[0]
    scenario = (first.get("name") or first.get("full_name") or "").strip()
    if scenario:
        return f"{scenario[:60]}{'…' if len(scenario) > 60 else ''} — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    return f"{filename} — {datetime.now().strftime('%Y-%m-%d %H:%M')}"


def _suite_summary(tests, max_suites=3):
    """Short summary of suite/feature names for Run History table (not the report format)."""
    if not tests:
        return ""
    seen = set()
    out = []
    for t in tests:
        s = (t.get("suite") or t.get("feature") or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    if not out:
        first = tests[0]
        n = (first.get("name") or first.get("full_name") or "").strip()
        return (n[:50] + "…") if len(n) > 50 else n
    display = ", ".join(out[:max_suites])
    if len(out) > max_suites:
        display += f" (+{len(out) - max_suites})"
    return display


def _test_summary(tests, max_tests=3):
    """Short summary of test names (prefer failed) for list views."""
    if not tests:
        return ""
    # Prefer failed tests first
    failed = [t for t in tests if (t.get("status") == "failed")]
    ordered = failed + [t for t in tests if t not in failed]

    seen = set()
    names = []
    for t in ordered:
        n = (t.get("name") or t.get("full_name") or "").strip()
        if n and n not in seen:
            seen.add(n)
            names.append(n)
    if not names:
        return ""
    display = ", ".join(names[:max_tests])
    if len(names) > max_tests:
        display += f" (+{len(names) - max_tests})"
    return display


def _sample_test_info(tests):
    """Pick a representative test name/suite for list views."""
    if not tests:
        return "", ""
    t = tests[0] or {}
    test_name = (t.get("name") or t.get("full_name") or "").strip()
    suite = (t.get("suite") or t.get("feature") or "").strip()
    return test_name, suite


def _infer_region_device_from_folder(folder_name: str, run_meta: dict, zip_name: str = "") -> dict:
    """
    Try to infer region + device from folder AND zip name, using known hints.
    Handles patterns like:
      - UK_desktop-chrome, DE_android-chrome, AT_iphone-safari
      - desktop-chrome_UK
      - allure_DE_android-chrome.zip
    Does NOT override explicit user-provided region/device.
    """
    out = dict(run_meta)
    # Treat "global"/"unknown" as not set
    if out.get("region") not in (None, "", "global") and out.get("device") not in (None, "", "unknown"):
        return out

    def _apply_hints(source: str, meta: dict):
        if not source:
            return meta
        text = source.strip()
        lower = text.lower()

        # Pattern: REGION_DEVICE e.g. AT_android-chrome, UK_desktop-chrome
        m = re.search(r"([A-Z]{2})_(desktop-[a-z0-9-]+|android-[a-z0-9-]+|iphone-safari|tablet-[a-z0-9-]+)", text, re.IGNORECASE)
        if m:
            reg_hint = m.group(1).upper()
            dev_hint = m.group(2).lower()
            if not meta.get("region"):
                meta["region"] = reg_hint
            if not meta.get("device"):
                meta["device"] = dev_hint

        # First, look for known device ids as substrings
        if not meta.get("device"):
            for dev in KNOWN_DEVICES:
                if dev in lower:
                    meta["device"] = dev
                    break
        # Then, look for known region ids (case-insensitive)
        if not meta.get("region"):
            t_upper = text.upper()
            for reg in KNOWN_REGIONS:
                if reg.upper() in t_upper:
                    meta["region"] = reg
                    break
        return meta

    # Apply hints from folder name and then from zip name
    out = _apply_hints(folder_name or "", out)
    out = _apply_hints(zip_name or "", out)
    return out


def _enrich_run_from_tests_file(run: dict) -> dict:
    """
    Backfill list-view fields for older runs that predate these keys.
    Recomputes passed/failed/skipped/pass_rate from the test file so dashboard
    "Latest run distribution" and list views show correct values.
    """
    run2 = dict(run)
    try:
        tests = _read_tests(run.get("id", ""))
    except Exception:
        tests = []
    # Recompute distribution from test file so displayed values are correct
    if tests:
        total = len(tests)
        passed = sum(1 for t in tests if t.get("status") == "passed")
        failed = sum(1 for t in tests if t.get("status") == "failed")
        skipped = total - passed - failed
        run2["total"] = total
        run2["passed"] = passed
        run2["failed"] = failed
        run2["skipped"] = skipped
        run2["pass_rate"] = pct(passed, total)
        run2["duration_ms"] = sum(t.get("duration_ms", 0) for t in tests)
    # Backfill summary fields if missing
    if not run2.get("test_summary") or not run2.get("suite_summary"):
        test_name, suite = _sample_test_info(tests)
        run2.setdefault("suite_summary", _suite_summary(tests))
        run2.setdefault("test_summary", _test_summary(tests))
        run2.setdefault("sample_test", test_name)
        run2.setdefault("sample_suite", suite)
    # If region/device are still generic, try to infer from run name / source_file
    if (run2.get("region") in ("", None, "global")) or (run2.get("device") in ("", None, "unknown")):
        hint_text = " ".join([
            str(run2.get("name","")),
            str(run2.get("source_file","")),
        ])
        run2 = _infer_region_device_from_folder(hint_text, run2)
    return run2

def _batch_aggregate(runs: list) -> dict:
    total_tests = sum(safe_int(r.get("total", 0)) for r in runs)
    passed = sum(safe_int(r.get("passed", 0)) for r in runs)
    failed = sum(safe_int(r.get("failed", 0)) for r in runs)
    skipped = sum(safe_int(r.get("skipped", 0)) for r in runs)
    dur = sum(safe_int(r.get("duration_ms", 0)) for r in runs)
    pass_rate = pct(passed, total_tests)

    regs = sorted({(r.get("region") or "").strip() for r in runs if (r.get("region") or "").strip()})
    devs = sorted({(r.get("device") or "").strip() for r in runs if (r.get("device") or "").strip()})
    envs = sorted({(r.get("env") or "").strip() for r in runs if (r.get("env") or "").strip()})

    # created_at range
    dts = [ _dt_from_iso(r.get("created_at","")) for r in runs ]
    dts = [d for d in dts if d]
    created_min = min(dts).isoformat() if dts else ""
    created_max = max(dts).isoformat() if dts else ""

    return {
        "run_count": len(runs),
        "total_tests": total_tests,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "duration_ms": dur,
        "pass_rate": pass_rate,
        "regions": regs,
        "devices": devs,
        "envs": envs,
        "created_at_min": created_min,
        "created_at_max": created_max,
    }


def api_batches(params=None):
    """
    List consolidated batches (multi-region/device imports).
    """
    runs = _read_runs()
    bm = defaultdict(list)
    for r in runs:
        bid = (r.get("batch_id") or "").strip()
        if bid:
            bm[bid].append(_enrich_run_from_tests_file(r))

    out = []
    for bid, rs in bm.items():
        agg = _batch_aggregate(rs)
        # Pick batch naming from any run (they should match)
        anyr = rs[0] if rs else {}
        # Representative test/suite summaries for list view
        rep_test = anyr.get("test_summary","") if isinstance(anyr, dict) else ""
        rep_suite = anyr.get("suite_summary","") if isinstance(anyr, dict) else ""
        out.append({
            "id": bid,
            "name": anyr.get("batch_name") or f"Batch {bid[:8]}",
            "created_at": anyr.get("batch_created_at") or anyr.get("created_at",""),
            "test_summary": rep_test,
            "suite_summary": rep_suite,
            **agg,
        })
    # newest first
    out.sort(key=lambda b: b.get("created_at",""), reverse=True)
    return 200, out


def api_batch_detail(batch_id: str):
    runs = [_enrich_run_from_tests_file(r) for r in _read_runs()
            if (r.get("batch_id") or "").strip() == (batch_id or "").strip()]
    if not runs:
        return 404, {"error": "Batch not found"}
    agg = _batch_aggregate(runs)

    # breakdown by region/device from runs
    by_region = defaultdict(lambda: {"runs":0,"total":0,"passed":0,"failed":0})
    by_device = defaultdict(lambda: {"runs":0,"total":0,"passed":0,"failed":0,"device_type":""})
    for r in runs:
        reg = r.get("region","global")
        dev = r.get("device","unknown")
        by_region[reg]["runs"] += 1
        by_region[reg]["total"] += safe_int(r.get("total",0))
        by_region[reg]["passed"] += safe_int(r.get("passed",0))
        by_region[reg]["failed"] += safe_int(r.get("failed",0))

        by_device[dev]["runs"] += 1
        by_device[dev]["total"] += safe_int(r.get("total",0))
        by_device[dev]["passed"] += safe_int(r.get("passed",0))
        by_device[dev]["failed"] += safe_int(r.get("failed",0))
        by_device[dev]["device_type"] = r.get("device_type","") or by_device[dev]["device_type"]

    br = sorted([{
        "region": k,
        "runs": v["runs"],
        "avg_pass_rate": round(pct(v["passed"], v["total"]), 2),
        "total_failed": v["failed"],
    } for k,v in by_region.items()], key=lambda x: x["region"])

    bd = sorted([{
        "device": k,
        "device_type": v["device_type"],
        "runs": v["runs"],
        "avg_pass_rate": round(pct(v["passed"], v["total"]), 2),
        "total_failed": v["failed"],
    } for k,v in by_device.items()], key=lambda x: x["device"])

    anyr = runs[0]

    # Collect tests across all runs for test-level view
    tests = []
    for r in runs:
        rid = r.get("id","")
        for t in _read_tests(rid):
            tests.append({
                "run_id": rid,
                "run_name": r.get("name",""),
                "region": r.get("region",""),
                "device": r.get("device",""),
                "env": r.get("env",""),
                "name": t.get("name",""),
                "suite": t.get("suite","") or t.get("feature",""),
                "status": t.get("status",""),
                "duration_ms": t.get("duration_ms",0),
                "is_flaky": bool(t.get("is_flaky")),
            })
    return 200, {
        "batch": {
            "id": batch_id,
            "name": anyr.get("batch_name") or f"Batch {batch_id[:8]}",
            "created_at": anyr.get("batch_created_at") or anyr.get("created_at",""),
            **agg,
        },
        "runs": runs,
        "tests": tests,
        "by_region": br,
        "by_device": bd,
    }


def api_batch_export(batch_id: str, params):
    fmt = (params.get("format", ["html"])[0] or "html").lower()
    c, d = api_batch_detail(batch_id)
    if c != 200:
        return c, d
    batch = d["batch"]; runs = d["runs"]; br = d["by_region"]; bd = d["by_device"]

    if fmt not in ("html", "md", "markdown"):
        return 400, {"error": "format must be html or md"}

    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", batch.get("name","batch"))[:80] or "batch"
    if fmt == "html":
        html = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>{batch.get('name','Consolidated QA Result')}</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;margin:24px;color:#111}}
h1{{margin:0 0 8px}} .meta{{color:#444;margin-bottom:16px}}
table{{border-collapse:collapse;width:100%;margin:14px 0}}
th,td{{border:1px solid #ddd;padding:8px;font-size:12px;vertical-align:top}}
th{{background:#f6f6f6;text-align:left}}
.kpi{{display:flex;gap:14px;flex-wrap:wrap;margin:12px 0}}
.card{{border:1px solid #ddd;border-radius:8px;padding:10px 12px;min-width:140px}}
.good{{color:#0a7}} .bad{{color:#d33}}
</style></head><body>
<h1>Consolidated QA Results</h1>
<div class="meta"><b>Batch:</b> {batch.get('name','')}<br/>
<b>Created:</b> {batch.get('created_at','')}<br/>
<b>Regions:</b> {", ".join(batch.get("regions",[])) or "—"}<br/>
<b>Devices:</b> {", ".join(batch.get("devices",[])) or "—"}</div>

<div class="kpi">
  <div class="card"><b>Runs</b><div>{batch.get("run_count",0)}</div></div>
  <div class="card"><b>Total tests</b><div>{batch.get("total_tests",0)}</div></div>
  <div class="card"><b>Failed</b><div class="bad">{batch.get("failed",0)}</div></div>
  <div class="card"><b>Pass rate</b><div class="good">{batch.get("pass_rate",0)}%</div></div>
</div>

<h2>By region</h2>
<table><thead><tr><th>Region</th><th>Runs</th><th>Avg pass rate</th><th>Total failed</th></tr></thead><tbody>
{''.join(f"<tr><td>{x['region']}</td><td>{x['runs']}</td><td>{x['avg_pass_rate']}%</td><td>{x['total_failed']}</td></tr>" for x in br)}
</tbody></table>

<h2>By device</h2>
<table><thead><tr><th>Device</th><th>Type</th><th>Runs</th><th>Avg pass rate</th><th>Total failed</th></tr></thead><tbody>
{''.join(f"<tr><td>{x['device']}</td><td>{x.get('device_type','')}</td><td>{x['runs']}</td><td>{x['avg_pass_rate']}%</td><td>{x['total_failed']}</td></tr>" for x in bd)}
</tbody></table>

<h2>Runs in this batch</h2>
<table><thead><tr><th>Run name</th><th>Test</th><th>Suite</th><th>Region</th><th>Device</th><th>Env</th><th>Pass%</th><th>Total</th><th>Failed</th><th>Date</th></tr></thead><tbody>
{''.join(f"<tr><td>{r.get('name','')}</td><td>{r.get('sample_test','')}</td><td>{r.get('sample_suite','') or r.get('suite_summary','')}</td><td>{r.get('region','')}</td><td>{r.get('device','')}</td><td>{r.get('env','')}</td><td>{r.get('pass_rate',0)}%</td><td>{r.get('total',0)}</td><td>{r.get('failed',0)}</td><td>{r.get('created_at','')}</td></tr>" for r in runs)}
</tbody></table>

</body></html>"""
        return 200, {
            "filename": f"{safe_name}_consolidated.html",
            "mime": "text/html; charset=utf-8",
            "content": html,
        }

    # Markdown (good for Confluence paste / wiki pages)
    md = []
    md.append(f"# Consolidated QA Results\n")
    md.append(f"**Batch:** {batch.get('name','')}\n")
    md.append(f"**Created:** {batch.get('created_at','')}\n")
    md.append(f"**Regions:** {', '.join(batch.get('regions',[])) or '—'}\n")
    md.append(f"**Devices:** {', '.join(batch.get('devices',[])) or '—'}\n")
    md.append(f"\n## Summary\n")
    md.append(f"- Runs: {batch.get('run_count',0)}\n")
    md.append(f"- Total tests: {batch.get('total_tests',0)}\n")
    md.append(f"- Failed: {batch.get('failed',0)}\n")
    md.append(f"- Pass rate: {batch.get('pass_rate',0)}%\n")

    md.append(f"\n## By region\n")
    md.append("| Region | Runs | Avg pass rate | Total failed |\n|---|---:|---:|---:|\n")
    for x in br:
        md.append(f"| {x['region']} | {x['runs']} | {x['avg_pass_rate']}% | {x['total_failed']} |\n")

    md.append(f"\n## By device\n")
    md.append("| Device | Type | Runs | Avg pass rate | Total failed |\n|---|---|---:|---:|---:|\n")
    for x in bd:
        md.append(f"| {x['device']} | {x.get('device_type','')} | {x['runs']} | {x['avg_pass_rate']}% | {x['total_failed']} |\n")

    md.append(f"\n## Runs in this batch\n")
    md.append("| Run name | Test | Suite | Region | Device | Env | Pass% | Total | Failed | Date |\n|---|---|---|---|---|---|---:|---:|---:|---|\n")
    for r in runs:
        md.append(f"| {r.get('name','')} | {r.get('sample_test','')} | {r.get('sample_suite','') or r.get('suite_summary','')} | {r.get('region','')} | {r.get('device','')} | {r.get('env','')} | {r.get('pass_rate',0)}% | {r.get('total',0)} | {r.get('failed',0)} | {r.get('created_at','')} |\n")

    return 200, {
        "filename": f"{safe_name}_consolidated.md",
        "mime": "text/markdown; charset=utf-8",
        "content": "".join(md),
    }


def api_batch_create(params):
    """
    Create a consolidated batch from existing runs.

    Primary key: build_id (exact match).
    If build_id is empty, optionally supports run_name_prefix.
    """
    build_id = (params.get("build_id", [""])[0] or "").strip()
    name_prefix = (params.get("run_name_prefix", [""])[0] or "").strip()
    batch_name = (params.get("batch_name", [""])[0] or "").strip()

    if not build_id and not name_prefix:
        return 400, {"error": "build_id or run_name_prefix is required"}

    all_runs = _read_runs()
    selected = []
    for r in all_runs:
        if build_id and (r.get("build_id","").strip() == build_id):
            selected.append(r)
        elif (not build_id) and name_prefix and r.get("name","").startswith(name_prefix):
            selected.append(r)

    if not selected:
        return 404, {"error": "No runs found for the given key"}

    new_batch_id = str(uuid.uuid4())
    created_at = now_iso()
    if not batch_name:
        batch_name = build_id or name_prefix or f"Batch {new_batch_id[:8]}"

    id_set = {r["id"] for r in selected if r.get("id")}
    updated = []
    for r in all_runs:
        if r.get("id") in id_set:
            r = dict(r)
            r["batch_id"] = new_batch_id
            r["batch_name"] = batch_name
            r["batch_created_at"] = created_at
        updated.append(r)

    _write_runs(updated)
    # Return detail for the new batch
    return api_batch_detail(new_batch_id)


def api_batch_delete(batch_id: str):
    """Delete a batch by detaching it from all runs (does not delete runs)."""
    bid = (batch_id or "").strip()
    if not bid:
        return 400, {"error": "Batch ID required"}

    with _lock:
        runs = _read_runs()
        matched = [r for r in runs if (r.get("batch_id") or "").strip() == bid]
        if not matched:
            return 404, {"error": "Batch not found"}
        updated = []
        for r in runs:
            if (r.get("batch_id") or "").strip() == bid:
                r2 = dict(r)
                r2["batch_id"] = ""
                r2["batch_name"] = ""
                r2["batch_created_at"] = ""
                updated.append(r2)
            else:
                updated.append(r)
        _write_runs(updated)

    return 200, {"deleted": bid, "detached_runs": len(matched)}


# ── Persist a run ─────────────────────────────────────────────────────────────
def save_run(tests, fmt, meta, filename):
    run_id  = str(uuid.uuid4())
    total   = len(tests)
    passed  = sum(1 for t in tests if t["status"]=="passed")
    failed  = sum(1 for t in tests if t["status"]=="failed")
    skipped = total - passed - failed
    dur     = sum(t["duration_ms"] for t in tests)
    sample_test, sample_suite = _sample_test_info(tests)
    run = {
        "id":            run_id,
        "name":          _run_display_name(tests, filename, meta),
        "suite_summary": _suite_summary(tests),
        "test_summary":  _test_summary(tests),
        "sample_test":   sample_test,
        "sample_suite":  sample_suite,
        "batch_id":      meta.get("batch_id",""),
        "batch_name":    meta.get("batch_name",""),
        "batch_created_at": meta.get("batch_created_at",""),
        "format":        fmt,
        "region":        meta.get("region","global"),
        "device":      meta.get("device","unknown"),
        "device_type": meta.get("device_type","desktop"),
        "os_name":     meta.get("os_name",""),
        "browser":     meta.get("browser",""),
        "env":         meta.get("env","qa"),
        "branch":      meta.get("branch",""),
        "build_id":    meta.get("build_id",""),
        "total":       total,
        "passed":      passed,
        "failed":      failed,
        "skipped":     skipped,
        "duration_ms": dur,
        "pass_rate":   pct(passed, total),
        "created_at":  now_iso(),
        "source_file": filename,
    }
    with _lock:
        runs = _read_runs()
        runs.insert(0, run)
        _write_runs(runs)
        _write_tests(run_id, tests)
    return run_id, run

# ── API ───────────────────────────────────────────────────────────────────────
def api_upload(handler, body):
    ctype = handler.headers.get("Content-Type","")
    if "multipart/form-data" not in ctype:
        return 400, {"error": "multipart/form-data required"}
    boundary = next((p.strip()[9:].strip('"') for p in ctype.split(";")
                     if p.strip().startswith("boundary=")), None)
    if not boundary:
        return 400, {"error": "No boundary"}

    files = []; meta = {}
    for part in body.split(f"--{boundary}".encode())[1:]:
        if part.strip() in (b"--", b"--\r\n", b""): continue
        if b"\r\n\r\n" not in part: continue
        hdr_b, content = part.split(b"\r\n\r\n", 1)
        content = content.rstrip(b"\r\n--")
        hdr = hdr_b.decode("utf-8","replace")
        cd = re.search(r'Content-Disposition:[^\r\n]+name="([^"]+)"', hdr)
        fn = re.search(r'filename="([^"]+)"', hdr)
        if not cd: continue
        if fn: files.append((fn.group(1), content))
        else:  meta[cd.group(1)] = content.decode("utf-8","replace").strip()

    if not files:
        return 400, {"error": "No files found"}

    # One batch per upload request (even if multiple files)
    batch_id = str(uuid.uuid4())
    meta = dict(meta)
    meta["batch_id"] = batch_id
    meta["batch_created_at"] = now_iso()
    meta["batch_name"] = meta.get("run_name") or f"Import {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    results = []
    for filename, content_bytes in files:
        run_id = str(uuid.uuid4())
        try:
            tests, fmt = auto_parse(content_bytes, filename, meta, run_id)
            run_id, run_info = save_run(tests, fmt, meta, filename)
            results.append({"run_id":run_id,"filename":filename,
                            "format":fmt,"tests":len(tests),"run":run_info})
        except Exception as e:
            results.append({"filename":filename,"error":str(e)})
    return 200, {"results": results}


def api_upload_zip(handler, body):
    """
    Accept a ZIP file containing an allure-results/ folder (or any folder
    of Allure JSON files).  Also handles a flat zip of multiple allure *.json
    files with no subfolder.

    Multipart form fields (same as /api/upload):
      file=<zip file>
      region, device, device_type, env, run_name, branch, build_id, …
    """
    ctype = handler.headers.get("Content-Type","")
    if "multipart/form-data" not in ctype:
        return 400, {"error": "multipart/form-data required"}
    boundary = next((p.strip()[9:].strip('"') for p in ctype.split(";")
                     if p.strip().startswith("boundary=")), None)
    if not boundary:
        return 400, {"error": "No boundary"}

    zip_files = []; meta = {}
    for part in body.split(f"--{boundary}".encode())[1:]:
        if part.strip() in (b"--", b"--\r\n", b""): continue
        if b"\r\n\r\n" not in part: continue
        hdr_b, content_bytes = part.split(b"\r\n\r\n", 1)
        content_bytes = content_bytes.rstrip(b"\r\n--")
        hdr = hdr_b.decode("utf-8","replace")
        cd  = re.search(r'Content-Disposition:[^\r\n]+name="([^"]+)"', hdr)
        fn  = re.search(r'filename="([^"]+)"', hdr)
        if not cd: continue
        if fn: zip_files.append((fn.group(1), content_bytes))
        else:  meta[cd.group(1)] = content_bytes.decode("utf-8","replace").strip()

    if not zip_files:
        return 400, {"error": "No ZIP file found"}

    results = []
    for zip_name, zip_bytes in zip_files:
        batch_id = str(uuid.uuid4())
        base_meta = dict(meta)
        # Infer region/device from the zip name itself if user didn't supply them
        base_meta = _infer_region_device_from_folder("", base_meta, zip_name)
        base_meta["batch_id"] = batch_id
        base_meta["batch_created_at"] = now_iso()
        base_meta["batch_name"] = base_meta.get("run_name") or (zip_name[:-4] if zip_name.lower().endswith(".zip") else zip_name)
        run_id = str(uuid.uuid4())
        try:
            if not zipfile.is_zipfile(io.BytesIO(zip_bytes)):
                # Maybe they uploaded a single JSON file via this endpoint by mistake
                tests, fmt = auto_parse(zip_bytes, zip_name, base_meta, run_id)
                run_id2, run_info = save_run(tests, fmt, base_meta, zip_name)
                results.append({"run_id":run_id2,"filename":zip_name,
                                 "format":fmt,"tests":len(tests),"run":run_info})
                continue

            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                all_names = zf.namelist()

                # ── Detect structure ─────────────────────────────────────────
                # Case A: all files are in a single subfolder (allure-results/)
                # Case B: files are at the root of the zip
                # Case C: multiple subfolders (one folder per test run)

                # Strip common prefix (e.g. "allure-results/")
                # Find all directories that contain .json files
                json_files_in_zip = [n for n in all_names if n.lower().endswith(".json") and not n.endswith("/")]

                if not json_files_in_zip:
                    results.append({"filename":zip_name,
                                    "error": "ZIP contains no JSON files"})
                    continue

                # Group by top-level directory
                folder_map = defaultdict(dict)  # folder_prefix -> {filename: bytes}
                for name in all_names:
                    if name.endswith("/") or "__MACOSX" in name:
                        continue
                    parts = name.split("/")
                    if len(parts) == 1:
                        # File at root level → put in "" bucket
                        folder_map[""][parts[0]] = zf.read(name)
                    else:
                        # File in a subfolder → top-level folder is the bucket
                        top = parts[0]
                        rel = "/".join(parts[1:])
                        folder_map[top][rel] = zf.read(name)

                # Remove the "" bucket if other folders also exist (prefer named folders)
                if len(folder_map) > 1 and "" in folder_map:
                    del folder_map[""]

                # ── Parse each folder as one run ─────────────────────────────
                for folder_name, files_dict in sorted(folder_map.items()):
                    if not any(f.lower().endswith(".json") for f in files_dict):
                        continue   # skip folders with no JSON

                    # Build run-specific meta (infer region/device from folder + zip name)
                    run_meta = _infer_region_device_from_folder(folder_name, base_meta, zip_name)
                    if folder_name and folder_name not in ("allure-results","results","output","report"):
                        # If the folder name encodes device/region info, try to use it
                        fl = folder_name.lower()
                        if not run_meta.get("run_name"):
                            run_meta["run_name"] = f"{zip_name[:-4]} / {folder_name}"
                    elif not run_meta.get("run_name"):
                        run_meta["run_name"] = zip_name[:-4] if zip_name.lower().endswith(".zip") else zip_name

                    sub_run_id = str(uuid.uuid4())
                    try:
                        tests, fmt = parse_allure_json_folder(files_dict, run_meta, sub_run_id)
                        sub_run_id2, run_info = save_run(tests, fmt, run_meta,
                                                          f"{zip_name}/{folder_name}" if folder_name else zip_name)
                        label = f"{zip_name} / {folder_name}" if folder_name else zip_name
                        results.append({"run_id":sub_run_id2,"filename":label,
                                         "format":fmt,"tests":len(tests),"run":run_info})
                    except Exception as e:
                        results.append({"filename":f"{zip_name}/{folder_name}","error":str(e)})

        except Exception as e:
            traceback.print_exc()
            results.append({"filename":zip_name,"error":str(e)})

    return 200, {"results": results}


def api_summary(params):
    all_runs = _read_runs()
    days     = safe_int(params.get("days",["30"])[0], 30)
    filtered = filter_runs(all_runs,
                           params.get("region",[""])[0],
                           params.get("device",[""])[0],
                           params.get("env",[""])[0], days)
    filtered = _sort_runs_newest_first(filtered)
    tr = len(filtered)
    tt = sum(safe_int(r.get("total", 0)) for r in filtered)
    tp = sum(safe_int(r.get("passed", 0)) for r in filtered)
    tf = sum(safe_int(r.get("failed", 0)) for r in filtered)
    ts = sum(safe_int(r.get("skipped", 0)) for r in filtered)
    if ts == 0 and tt > 0:
        ts = tt - tp - tf  # fallback if skipped not stored
    ap = pct(tp, tt)   # correct: total passed / total tests

    all_regions = sorted({r["region"] for r in all_runs}
                         | {"global","us-east","us-west","eu-west","ap-southeast","ap-south"})
    all_devices = sorted({r["device"] for r in all_runs}
                         | {"desktop-chrome","desktop-firefox","mobile-ios","mobile-android"})
    return 200, {
        "totals": {"total_runs":tr,"total_tests":tt,"total_passed":tp,
                   "total_failed":tf,"total_skipped":max(0, ts),"avg_pass_rate":round(ap,2)},
        "regions": all_regions,
        "devices": all_devices,
        "recent":  [_enrich_run_from_tests_file(r) for r in filtered[:5]],
    }


def api_runs(params):
    all_runs = _read_runs()
    days     = safe_int(params.get("days",["30"])[0], 30)
    limit    = min(safe_int(params.get("limit",["200"])[0]), 1000)
    offset   = safe_int(params.get("offset",["0"])[0])
    filtered = filter_runs(all_runs,
                           params.get("region",[""])[0],
                           params.get("device",[""])[0],
                           params.get("env",[""])[0], days)
    filtered = _sort_runs_newest_first(filtered)
    page = filtered[offset:offset+limit]
    return 200, {"runs": [_enrich_run_from_tests_file(r) for r in page], "total": len(filtered)}


def api_run_detail(run_id):
    run = next((r for r in _read_runs() if r["id"] == run_id), None)
    if not run:
        return 404, {"error": "Run not found"}
    tests = _read_tests(run_id)
    sm = defaultdict(lambda: {"total":0,"passed":0,"failed":0,"skipped":0,"dur":0})
    for t in tests:
        s = t.get("suite","Default")
        sm[s]["total"]   += 1
        sm[s]["passed"]  += t["status"]=="passed"
        sm[s]["failed"]  += t["status"]=="failed"
        sm[s]["skipped"] += t["status"]=="skipped"
        sm[s]["dur"]     += t.get("duration_ms",0)
    suites = sorted([{
        "suite":s,"total":v["total"],"passed":v["passed"],"failed":v["failed"],
        "skipped":v["skipped"],"avg_dur":round(v["dur"]/v["total"]) if v["total"] else 0
    } for s,v in sm.items()], key=lambda x: -x["failed"])
    return 200, {"run": run, "tests": tests, "suites": suites}


def api_trends(params):
    all_runs = _read_runs()
    days     = safe_int(params.get("days",["30"])[0], 30)
    filtered = filter_runs(all_runs,
                           params.get("region",[""])[0],
                           params.get("device",[""])[0],
                           params.get("env",[""])[0], days)

    # daily
    dm = defaultdict(lambda: {"runs":0,"total":0,"passed":0,"failed":0,"dur":0})
    for r in filtered:
        d = r["created_at"][:10]
        dm[d]["runs"]+=1; dm[d]["total"]+=r["total"]
        dm[d]["passed"]+=r["passed"]; dm[d]["failed"]+=r["failed"]
        dm[d]["dur"]+=r["duration_ms"]
    daily = sorted([{"day":d,"runs":v["runs"],"total_tests":v["total"],
        "total_passed":v["passed"],"total_failed":v["failed"],
        "avg_pass_rate":round(pct(v["passed"],v["total"]),2),
        "avg_duration":round(v["dur"]/v["runs"]) if v["runs"] else 0}
        for d,v in dm.items()], key=lambda x: x["day"])

    # by region
    rm = defaultdict(lambda: {"runs":0,"passed":0,"total":0,"failed":0})
    for r in filtered:
        k=r.get("region","global"); rm[k]["runs"]+=1
        rm[k]["total"]+=r["total"]; rm[k]["passed"]+=r["passed"]; rm[k]["failed"]+=r["failed"]
    by_region = sorted([{"region":k,"runs":v["runs"],
        "avg_pass_rate":round(pct(v["passed"],v["total"]),2),"total_failed":v["failed"]}
        for k,v in rm.items()], key=lambda x: x["avg_pass_rate"])

    # by device
    dvm = defaultdict(lambda: {"runs":0,"passed":0,"total":0,"failed":0,"dtype":""})
    for r in filtered:
        k=r.get("device","unknown"); dvm[k]["runs"]+=1
        dvm[k]["total"]+=r["total"]; dvm[k]["passed"]+=r["passed"]; dvm[k]["failed"]+=r["failed"]
        dvm[k]["dtype"]=r.get("device_type","desktop")
    by_device = sorted([{"device":k,"device_type":v["dtype"],"runs":v["runs"],
        "avg_pass_rate":round(pct(v["passed"],v["total"]),2),"total_failed":v["failed"]}
        for k,v in dvm.items()], key=lambda x: x["avg_pass_rate"])

    # flaky  (scan up to 50 recent runs)
    fm = defaultdict(lambda: {"n":0,"retries":0,"region":"","device":""})
    for r in filtered[:50]:
        for t in _read_tests(r["id"]):
            if t.get("is_flaky"):
                key = t["name"]+"||"+t.get("suite","")
                fm[key]["n"]+=1; fm[key]["retries"]+=t.get("retry_count",0)
                fm[key]["region"]=t.get("region",""); fm[key]["device"]=t.get("device","")
    flaky = sorted([{"name":k.split("||")[0],"suite":k.split("||")[1],
        "occurrences":v["n"],"retries":v["retries"],"region":v["region"],"device":v["device"]}
        for k,v in fm.items()], key=lambda x: -x["occurrences"])[:20]

    # top failures
    tfm = defaultdict(lambda: {"count":0,"suite":"","error":"","region":"","device":""})
    for r in filtered[:50]:
        for t in _read_tests(r["id"]):
            if t["status"]=="failed":
                key = t["name"]+"||"+t.get("suite","")
                tfm[key]["count"]+=1; tfm[key]["suite"]=t.get("suite","")
                tfm[key]["error"]=t.get("error_msg","")
                tfm[key]["region"]=t.get("region",""); tfm[key]["device"]=t.get("device","")
    top_failures = sorted([{"name":k.split("||")[0],"suite":v["suite"],
        "fail_count":v["count"],"error_msg":v["error"],"region":v["region"],"device":v["device"]}
        for k,v in tfm.items()], key=lambda x: -x["fail_count"])[:20]

    return 200, {"daily":daily,"by_region":by_region,"by_device":by_device,
                 "flaky":flaky,"top_failures":top_failures}


def api_compare(params):
    ids = [i.strip() for i in params.get("ids",[""])[0].split(",") if i.strip()][:6]
    runs = [r for r in _read_runs() if r["id"] in ids]
    return 200, [_enrich_run_from_tests_file(r) for r in runs]


def api_delete(run_id):
    with _lock:
        runs = _read_runs()
        if not any(r["id"] == run_id for r in runs):
            return 404, {"error": "Run not found"}
        runs = [r for r in runs if r["id"] != run_id]
        _write_runs(runs)
        _delete_run(run_id)
    return 200, {"deleted": run_id}


def api_db_info():
    runs = _read_runs()
    files = list(TESTS_DIR.glob("*.json"))
    size  = sum(f.stat().st_size for f in ([RUNS_FILE]+files) if f.exists())
    return 200, {
        "storage":       "Plain JSON — open in any text editor",
        "runs_file":     str(RUNS_FILE),
        "tests_dir":     str(TESTS_DIR),
        "run_count":     len(runs),
        "test_files":    len(files),
        "total_size_kb": round(size/1024, 1),
        "backup":        "Copy the entire data/ folder",
        "edit_tip":      "Open data/runs.json in VS Code / Notepad to edit metadata directly",
    }

def api_version():
    return 200, {
        "version": APP_VERSION,
        "server_file": str(Path(__file__).resolve()),
        "base_dir": str(BASE_DIR.resolve()),
    }


def api_regions():
    """
    Return regions derived from uploaded runs.
    Frontend expects: [{id, name}, ...]
    """
    runs = _read_runs()
    regs = sorted({(r.get("region") or "").strip() for r in runs if (r.get("region") or "").strip()})
    # Provide stable defaults too (useful before any uploads)
    defaults = ["global", "us-east", "us-west", "eu-west", "ap-southeast", "ap-south"]
    merged = []
    seen = set()
    for x in regs + defaults:
        if x and x not in seen:
            seen.add(x)
            merged.append({"id": x, "name": x})
    return 200, merged


def api_devices():
    """
    Return devices derived from uploaded runs.
    Frontend expects: [{id, name}, ...]
    """
    runs = _read_runs()
    observed = sorted({(r.get("device") or "").strip() for r in runs if (r.get("device") or "").strip()})

    # Canonical devices (match Import UI values)
    catalog = [
        ("desktop-chrome",  "Desktop Chrome"),
        ("desktop-firefox", "Desktop Firefox"),
        ("desktop-safari",  "Desktop Safari"),
        ("desktop-edge",    "Desktop Edge"),
        ("headless-chrome", "Headless Chrome (CI)"),
        ("iphone-safari",   "iPhone Safari (iOS)"),
        ("android-chrome",  "Android Chrome"),
        ("android-samsung", "Android Samsung Browser"),
        ("tablet-ipad",     "iPad Safari"),
        ("tablet-android",  "Android Tablet Chrome"),
        ("api-backend",     "API / Backend (no browser)"),
    ]

    out = []
    seen = set()

    # Prefer showing only devices that exist in uploaded runs.
    # If nothing uploaded yet, show full catalog so user can pick filters.
    if observed:
        for dev_id, dev_name in catalog:
            if dev_id in observed and dev_id not in seen:
                seen.add(dev_id)
                out.append({"id": dev_id, "name": dev_name})
        # Include any unknown observed devices at the end (raw id as name)
        for x in observed:
            if x and x not in seen:
                seen.add(x)
                out.append({"id": x, "name": x})
    else:
        for dev_id, dev_name in catalog:
            out.append({"id": dev_id, "name": dev_name})

    return 200, out


def api_builds():
    """
    List distinct build_ids from existing runs (for batch creation dropdown).
    """
    runs = _read_runs()
    builds = defaultdict(lambda: {"count":0,"name_samples":set()})
    for r in runs:
        bid = (r.get("build_id") or "").strip()
        if not bid:
            continue
        builds[bid]["count"] += 1
        if r.get("name"):
            builds[bid]["name_samples"].add(r["name"])
    out = []
    for bid, info in builds.items():
        sample_name = sorted(info["name_samples"])[0] if info["name_samples"] else ""
        out.append({
            "id": bid,
            "label": bid,
            "run_count": info["count"],
            "sample_name": sample_name,
        })
    out.sort(key=lambda x: x["id"])
    return 200, out


def api_reset():
    """Clear all runs and test files — reset dashboard to empty state."""
    with _lock:
        _write_runs([])
        for p in TESTS_DIR.glob("*.json"):
            try:
                p.unlink()
            except Exception:
                pass
    return 200, {"ok": True, "message": "Dashboard reset. All runs and test data cleared."}


# ── HTTP Handler ──────────────────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  [{datetime.now().strftime('%H:%M:%S')}]", fmt % args)

    def _json(self, code, data):
        body = json.dumps(data, default=str, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        try:
            data = Path(path).read_bytes()
            mime, _ = mimetypes.guess_type(str(path))
            self.send_response(200)
            self.send_header("Content-Type", mime or "text/plain")
            self.send_header("Content-Length", len(data))
            # Prevent caching dashboard HTML so code changes show after refresh
            if path.suffix.lower() == ".html":
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except FileNotFoundError:
            self.send_response(404); self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        if path in ("","/"): self._file(BASE_DIR/"public"/"index.html"); return
        if not path.startswith("/api"):
            fp = BASE_DIR / "public" / path.lstrip("/")
            if fp.exists() and fp.is_file(): self._file(fp); return

        try:
            if   path == "/api/summary":   c,d = api_summary(params)
            elif path == "/api/runs":       c,d = api_runs(params)
            elif re.match(r"^/api/runs/[^/]+/detail$", path):
                                            c,d = api_run_detail(path.split("/")[3])
            elif path == "/api/trends":    c,d = api_trends(params)
            elif path == "/api/compare":   c,d = api_compare(params)
            elif path == "/api/batches":   c,d = api_batches(params)
            elif re.match(r"^/api/batches/[^/]+/detail$", path):
                                            c,d = api_batch_detail(path.split("/")[3])
            elif re.match(r"^/api/batches/[^/]+/export$", path):
                                            c,d = api_batch_export(path.split("/")[3], params)
            elif path == "/api/regions":   c,d = api_regions()
            elif path == "/api/devices":   c,d = api_devices()
            elif path == "/api/builds":    c,d = api_builds()
            elif path == "/api/version":   c,d = api_version()
            elif path == "/api/db":        c,d = api_db_info()
            else:                          c,d = 404, {"error":f"Unknown: {path}"}
            self._json(c,d)
        except Exception as e:
            traceback.print_exc(); self._json(500,{"error":str(e)})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)
        body = self.rfile.read(safe_int(self.headers.get("Content-Length",0)))
        try:
            if path == "/api/upload":        c,d = api_upload(self, body)
            elif path == "/api/upload-zip":  c,d = api_upload_zip(self, body)
            elif path == "/api/reset":       c,d = api_reset()
            elif path == "/api/batches/create": c,d = api_batch_create(params)
            else:                            c,d = 404, {"error":"Not found"}
            self._json(c,d)
        except Exception as e:
            traceback.print_exc(); self._json(500,{"error":str(e)})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = (parsed.path or "/").rstrip("/")
        try:
            # Match /api/batches/<id> (non-regex to avoid edge parsing issues)
            if path.startswith("/api/batches/"):
                parts = path.split("/")
                # ["", "api", "batches", "<id>"]
                if len(parts) >= 4 and parts[3]:
                    c, d = api_batch_delete(parts[3])
                    self._json(c, d)
                    return
            # Match /api/runs/<id> or /api/runs/<id>/ (optional trailing slash)
            m = re.match(r"^/api/runs/([^/]+)/?$", path)
            if m:
                run_id = m.group(1)
                if not run_id:
                    c, d = 400, {"error": "Run ID required"}
                else:
                    c, d = api_delete(run_id)
            else:
                c, d = 404, {"error": "Not found"}
            self._json(c, d)
        except Exception as e:
            self._json(500, {"error": str(e)})

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Use ASCII-only banner for Windows consoles that can't print box-drawing chars
    print(f"""
  ---------------------------------------------------
             QA Pulse - AI Test Dashboard
  ---------------------------------------------------
    Dashboard : http://localhost:{PORT}
    Data store: data/runs.json + data/tests/
    Storage   : Plain JSON (edit in any text editor)
    Stop      : Ctrl+C
  ---------------------------------------------------
""")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("", PORT), Handler) as srv:
        srv.daemon_threads = True
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n  Stopped.")
