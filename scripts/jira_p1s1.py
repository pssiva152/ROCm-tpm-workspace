#!/usr/bin/env python3
"""
Fetch P1/S1 Jira tickets for a given ROCm version and output a markdown or HTML report.

Usage:
    # PowerShell:
    $env:JIRA_API_TOKEN = "your_api_token"
    $env:JIRA_EMAIL = "your.email@amd.com"
    python scripts/jira_p1s1.py --version "ROCm 7.13.0"
    python scripts/jira_p1s1.py --version "ROCm 7.13.0" --html
    python scripts/jira_p1s1.py --version "ROCm 7.13.0" --save

Auth:
    Uses Basic auth (Jira Cloud): base64(email:api_token).
    JIRA_API_TOKEN and JIRA_EMAIL are read from environment variables only.
    Never pass the token as a command-line argument.
"""

import argparse
import base64
import json
import os
import sys
import webbrowser
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

JIRA_BASE_URL = "https://amd-hub.atlassian.net"

STATUS_COLORS = {
    "Open":        "#e53935",
    "Triage":      "#fb8c00",
    "Queue":       "#f4c842",
    "In Progress": "#1e88e5",
    "Validate":    "#8e24aa",
    "Done":        "#43a047",
    "Discarded":   "#9e9e9e",
}


def get_auth_header() -> str:
    token = os.environ.get("JIRA_API_TOKEN", "").strip()
    email = os.environ.get("JIRA_EMAIL", "").strip()
    if not token:
        print("ERROR: JIRA_API_TOKEN environment variable is not set.", file=sys.stderr)
        print("  PowerShell: $env:JIRA_API_TOKEN = 'your_token'", file=sys.stderr)
        sys.exit(1)
    if not email:
        print("ERROR: JIRA_EMAIL environment variable is not set.", file=sys.stderr)
        print("  PowerShell: $env:JIRA_EMAIL = 'your.email@amd.com'", file=sys.stderr)
        sys.exit(1)
    credentials = base64.b64encode(f"{email}:{token}".encode()).decode()
    return f"Basic {credentials}"


def jira_search(auth_header: str, jql: str, fields: list[str], max_results: int = 100) -> list[dict]:
    """Run a JQL search and return all issues (auto-paginating via nextPageToken)."""
    all_issues = []
    next_page_token = None

    while True:
        params = {
            "jql": jql,
            "maxResults": max_results,
            "fields": ",".join(fields),
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token

        url = f"{JIRA_BASE_URL}/rest/api/3/search/jql?{urlencode(params)}"
        req = Request(url, headers={
            "Authorization": auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

        try:
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
        except HTTPError as e:
            body = e.read().decode()
            if e.code == 401:
                print("ERROR: Authentication failed. Check your JIRA_API_TOKEN.", file=sys.stderr)
            elif e.code == 400:
                print(f"ERROR: Bad JQL query — {body}", file=sys.stderr)
            else:
                print(f"ERROR: HTTP {e.code} — {body}", file=sys.stderr)
            sys.exit(1)
        except URLError as e:
            print(f"ERROR: Could not reach {JIRA_BASE_URL} — {e.reason}", file=sys.stderr)
            sys.exit(1)

        issues = data.get("issues", [])
        all_issues.extend(issues)

        if data.get("isLast", True) or not issues:
            break
        next_page_token = data.get("nextPageToken")
        if not next_page_token:
            break

    return all_issues


def safe_field(issue: dict, *path: str, default: str = "—") -> str:
    obj = issue
    for key in path:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key)
        if obj is None:
            return default
    return str(obj) if obj else default


def format_age(date_str: str) -> str:
    if not date_str:
        return "—"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - dt).days
        if days == 0:
            return "today"
        return f"{days}d ago"
    except ValueError:
        return date_str[:10]


def escape_html(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


PR_STATUS_COLORS = {
    "OPEN":     "#1e88e5",
    "MERGED":   "#43a047",
    "DECLINED": "#e53935",
}


def status_badge(status: str) -> str:
    color = STATUS_COLORS.get(status, "#757575")
    return f'<span class="badge" style="background:{color}">{escape_html(status)}</span>'


def pr_badge(pr_status: str, url: str, name: str) -> str:
    color = PR_STATUS_COLORS.get(pr_status.upper(), "#757575")
    short = escape_html(name[:50] + "…" if len(name) > 50 else name)
    return (
        f'<a href="{url}" target="_blank" class="pr-link" '
        f'style="border-color:{color};color:{color}" '
        f'title="{escape_html(name)}">'
        f'<span class="pr-status-dot" style="background:{color}"></span>'
        f'{short}</a>'
    )


def fetch_pr_data(auth_header: str, issue_id: str) -> list[dict]:
    """Fetch linked GitHub PRs for a single issue via the dev-status API."""
    params = urlencode({
        "issueId": issue_id,
        "applicationType": "GitHub",
        "dataType": "pullrequest",
    })
    req = Request(
        f"{JIRA_BASE_URL}/rest/dev-status/1.0/issue/detail?{params}",
        headers={"Authorization": auth_header, "Accept": "application/json"},
    )
    try:
        with urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        return data.get("detail", [{}])[0].get("pullRequests", [])
    except Exception:
        return []


def fetch_all_pr_data(auth_header: str, issues: list[dict]) -> dict[str, list[dict]]:
    """Fetch PR data for all issues in parallel. Returns {issue_key: [pr, ...]}."""
    result: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(fetch_pr_data, auth_header, issue["id"]): issue["key"]
            for issue in issues
        }
        for future in as_completed(futures):
            key = futures[future]
            result[key] = future.result()
    return result


RESOLVED_STATUSES = {"Done", "Discarded"}


# ---------------------------------------------------------------------------
# Snapshot helpers — save/load a compact JSON record per run for diffing
# ---------------------------------------------------------------------------

def snapshot_from_issues(issues: list[dict], version: str, timestamp: str) -> dict:
    return {
        "version": version,
        "timestamp": timestamp,
        "tickets": {
            issue["key"]: {
                "summary": safe_field(issue, "fields", "summary"),
                "status":   safe_field(issue, "fields", "status", "name"),
                "priority": safe_field(issue, "fields", "priority", "name"),
                "assessed_severity": safe_field(issue, "fields", "customfield_10417", "value", default=""),
                "assignee": safe_field(issue, "fields", "assignee", "displayName"),
            }
            for issue in issues
        },
    }


def save_snapshot(snapshot: dict, reports_dir: str, timestamp: str, version_slug: str) -> str:
    os.makedirs(reports_dir, exist_ok=True)
    path = os.path.normpath(os.path.join(
        reports_dir, f"{timestamp}-mainline-blockers-{version_slug}.json"
    ))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)
    return path


def load_previous_snapshot(reports_dir: str, version_slug: str, current_timestamp: str) -> dict | None:
    """Find and load the most recent snapshot for this version, excluding the current run."""
    pattern = f"-mainline-blockers-{version_slug}.json"
    try:
        candidates = sorted(
            [f for f in os.listdir(reports_dir) if f.endswith(pattern) and not f.startswith(current_timestamp)],
            reverse=True,
        )
    except FileNotFoundError:
        return None
    if not candidates:
        return None
    path = os.path.join(reports_dir, candidates[0])
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def compute_diff(prev: dict, curr: dict) -> dict:
    prev_tickets = prev.get("tickets", {})
    curr_tickets = curr.get("tickets", {})
    new_keys     = [k for k in curr_tickets if k not in prev_tickets]
    removed_keys = [k for k in prev_tickets if k not in curr_tickets]
    status_changes = {
        k: {"from": prev_tickets[k]["status"], "to": curr_tickets[k]["status"]}
        for k in curr_tickets
        if k in prev_tickets and curr_tickets[k]["status"] != prev_tickets[k]["status"]
    }
    return {
        "prev_timestamp": prev.get("timestamp", "?"),
        "prev_count": len(prev_tickets),
        "curr_count": len(curr_tickets),
        "delta": len(curr_tickets) - len(prev_tickets),
        "new": {k: curr_tickets[k] for k in new_keys},
        "removed": {k: prev_tickets[k] for k in removed_keys},
        "status_changes": status_changes,
    }


def print_diff(diff: dict) -> None:
    delta = diff["delta"]
    sign  = "+" if delta >= 0 else ""
    arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "—")
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  Changes vs last report ({diff['prev_timestamp']})", file=sys.stderr)
    print(f"  Total: {diff['prev_count']} → {diff['curr_count']}  {arrow} {sign}{delta}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    if diff["new"]:
        print(f"\n  NEW tickets ({len(diff['new'])}):", file=sys.stderr)
        for k, t in diff["new"].items():
            print(f"    + {k}  [{t['status']}]  {t['summary'][:60]}  {JIRA_BASE_URL}/browse/{k}", file=sys.stderr)
    if diff["removed"]:
        print(f"\n  REMOVED tickets ({len(diff['removed'])}):", file=sys.stderr)
        for k, t in diff["removed"].items():
            print(f"    - {k}  [{t['status']}]  {t['summary'][:60]}", file=sys.stderr)
    if diff["status_changes"]:
        print(f"\n  STATUS changes ({len(diff['status_changes'])}):", file=sys.stderr)
        for k, ch in diff["status_changes"].items():
            print(f"    ~ {k}  {ch['from']} → {ch['to']}", file=sys.stderr)
    if not diff["new"] and not diff["removed"] and not diff["status_changes"]:
        print("  No changes since last report.", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)


def build_issue_rows(issues: list[dict], pr_map: dict[str, list[dict]] | None = None) -> str:
    rows = ""
    for issue in issues:
        key = issue.get("key", "?")
        url = f"{JIRA_BASE_URL}/browse/{key}"
        summary = escape_html(safe_field(issue, "fields", "summary"))
        status = safe_field(issue, "fields", "status", "name")
        priority = safe_field(issue, "fields", "priority", "name")
        assignee = escape_html(safe_field(issue, "fields", "assignee", "displayName"))
        reporter = escape_html(safe_field(issue, "fields", "reporter", "displayName"))
        assessed_severity = escape_html(safe_field(issue, "fields", "customfield_10417", "value", default="—"))

        # Triage Assignment: selectedOptionsList[*].label (multi-select)
        triage_raw = (issue.get("fields") or {}).get("customfield_11403") or {}
        triage_labels = [o.get("label", "") for o in triage_raw.get("selectedOptionsList", [])]
        triage_assignment = escape_html(", ".join(triage_labels) if triage_labels else "—")

        due_date = escape_html(safe_field(issue, "fields", "duedate", default="—"))

        # Customer(s): array of strings or objects
        customers_raw = (issue.get("fields") or {}).get("customfield_11214") or []
        if isinstance(customers_raw, list):
            customers = ", ".join(
                c.get("name") or c.get("label") or c.get("value") or str(c) if isinstance(c, dict) else str(c)
                for c in customers_raw
            ) or "—"
        else:
            customers = str(customers_raw) if customers_raw else "—"
        customers = escape_html(customers)

        # PR(s) from dev-status
        prs_html = ""
        if pr_map is not None:
            prs = pr_map.get(key, [])
            if prs:
                prs_html = "<div class='pr-list'>" + "".join(
                    pr_badge(pr.get("status", ""), pr.get("url", "#"), pr.get("name", pr.get("id", "PR")))
                    for pr in prs
                ) + "</div>"
            else:
                prs_html = "<span style='color:#bbb'>—</span>"

        updated = format_age(safe_field(issue, "fields", "updated", default=""))
        created = format_age(safe_field(issue, "fields", "created", default=""))

        rows += f"""
        <tr>
          <td><a href="{url}" target="_blank" class="key-link">{key}</a></td>
          <td class="summary-cell">{summary}</td>
          <td>{status_badge(status)}</td>
          <td><span class="priority">{escape_html(priority)}</span></td>
          <td>{assessed_severity}</td>
          <td>{triage_assignment}</td>
          <td>{due_date}</td>
          <td>{customers}</td>
          <td>{assignee}</td>
          <td>{reporter}</td>
          <td class="pr-cell">{prs_html}</td>
          <td class="age">{updated}</td>
          <td class="age">{created}</td>
        </tr>"""
    return rows


def build_table(table_id: str, rows: str) -> str:
    headers = ["Key", "Summary", "Status", "Priority", "Assessed Severity", "Triage Assignment", "Due Date", "Customer(s)", "Assignee", "Reporter", "PR(s)", "Updated", "Created"]
    ths = "".join(
        f'<th onclick="sortTable(\'{table_id}\', {i})">'
        f'{h} <span class="sort-icon">⇅</span></th>'
        for i, h in enumerate(headers)
    )
    return f"""
    <div class="table-wrap">
      <table id="{table_id}">
        <thead><tr>{ths}</tr></thead>
        <tbody>{rows}
        </tbody>
      </table>
    </div>"""


def build_diff_html(diff: dict | None) -> str:
    """Render the Changes Since Last Report banner for the HTML page."""
    if diff is None:
        return '<div class="diff-banner diff-none">No previous report found — this is the first run for this version.</div>'

    delta  = diff["delta"]
    sign   = "+" if delta > 0 else ""
    arrow  = "▲" if delta > 0 else ("▼" if delta < 0 else "—")
    color  = "#c62828" if delta > 0 else ("#2e7d32" if delta < 0 else "#555")

    rows_new = "".join(
        f'<tr class="diff-new"><td><a href="{JIRA_BASE_URL}/browse/{k}" target="_blank">{k}</a></td>'
        f'<td>{escape_html(t["summary"][:80])}</td>'
        f'<td>{status_badge(t["status"])}</td>'
        f'<td><span style="color:#2e7d32;font-weight:700">NEW</span></td></tr>'
        for k, t in diff["new"].items()
    )
    rows_removed = "".join(
        f'<tr class="diff-removed"><td><a href="{JIRA_BASE_URL}/browse/{k}" target="_blank">{k}</a></td>'
        f'<td>{escape_html(t["summary"][:80])}</td>'
        f'<td>{status_badge(t["status"])}</td>'
        f'<td><span style="color:#c62828;font-weight:700">REMOVED</span></td></tr>'
        for k, t in diff["removed"].items()
    )
    rows_changed = "".join(
        f'<tr class="diff-changed"><td><a href="{JIRA_BASE_URL}/browse/{k}" target="_blank">{k}</a></td>'
        f'<td colspan="2"><span class="diff-from">{escape_html(ch["from"])}</span>'
        f' → <span class="diff-to">{escape_html(ch["to"])}</span></td>'
        f'<td><span style="color:#e65100;font-weight:700">STATUS</span></td></tr>'
        for k, ch in diff["status_changes"].items()
    )

    table = ""
    if rows_new or rows_removed or rows_changed:
        table = f"""
        <table class="diff-table">
          <thead><tr><th>Key</th><th>Summary / Change</th><th>Status</th><th>Change</th></tr></thead>
          <tbody>{rows_new}{rows_removed}{rows_changed}</tbody>
        </table>"""
    else:
        table = '<p class="diff-nochange">No ticket additions, removals, or status changes.</p>'

    return f"""
    <div class="diff-banner">
      <div class="diff-header">
        <span class="diff-title">Changes Since Last Report</span>
        <span class="diff-meta">vs {escape_html(diff["prev_timestamp"])}</span>
        <span class="diff-delta" style="color:{color}">{arrow} {sign}{delta} tickets
          ({diff['prev_count']} → {diff['curr_count']})</span>
        <span class="diff-pills">
          {f'<span class="diff-pill new">{len(diff["new"])} new</span>' if diff["new"] else ""}
          {f'<span class="diff-pill removed">{len(diff["removed"])} removed</span>' if diff["removed"] else ""}
          {f'<span class="diff-pill changed">{len(diff["status_changes"])} status changes</span>' if diff["status_changes"] else ""}
        </span>
      </div>
      {table}
    </div>"""


def build_html(issues: list[dict], version: str, jql: str, auth_header: str = "", diff: dict | None = None) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    pr_map: dict[str, list[dict]] = {}
    if auth_header:
        print("Fetching PR data from GitHub via Jira dev-status...", file=sys.stderr)
        pr_map = fetch_all_pr_data(auth_header, issues)
        pr_count = sum(len(v) for v in pr_map.values())
        print(f"Found {pr_count} linked PR(s) across {len(issues)} tickets.", file=sys.stderr)

    def is_resolved(i):
        return safe_field(i, "fields", "status", "name") in RESOLVED_STATUSES

    def is_p1_s1(i):
        priority = safe_field(i, "fields", "priority", "name")
        severity = safe_field(i, "fields", "customfield_10417", "value", default="")
        return priority in ("P1: High", "P1 (Gating)") and severity.startswith("S1")

    primary_blockers = [i for i in issues if not is_resolved(i) and is_p1_s1(i)]
    other_high = [i for i in issues if not is_resolved(i) and not is_p1_s1(i)]
    resolved = [i for i in issues if is_resolved(i)]

    # Count by status
    status_counts: dict[str, int] = {}
    for issue in issues:
        s = safe_field(issue, "fields", "status", "name")
        status_counts[s] = status_counts.get(s, 0) + 1

    summary_pills = "".join(
        f'<span class="pill" style="background:{STATUS_COLORS.get(s,"#757575")}">'
        f'{escape_html(s)}: {c}</span>'
        for s, c in sorted(status_counts.items())
    )

    primary_table = build_table("primary-table", build_issue_rows(primary_blockers, pr_map))
    other_table = build_table("other-table", build_issue_rows(other_high, pr_map))
    resolved_table = build_table("resolved-table", build_issue_rows(resolved, pr_map))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Mainline Blockers — {escape_html(version)}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #f5f6fa; color: #1a1a2e; font-size: 14px; }}
    header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
              color: white; padding: 24px 32px; }}
    header h1 {{ font-size: 22px; font-weight: 600; margin-bottom: 4px; }}
    header .meta {{ opacity: 0.6; font-size: 12px; }}
    .jql-bar {{ background: #0f3460; color: #a8d8ea; font-family: monospace;
                font-size: 11px; padding: 8px 32px; word-break: break-all; }}
    .container {{ padding: 24px 32px; }}
    .summary-bar {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 20px; }}
    .pill {{ color: white; padding: 4px 12px; border-radius: 20px;
             font-size: 12px; font-weight: 600; }}
    .total {{ font-size: 13px; color: #555; align-self: center; margin-left: auto; }}
    .section-header {{ font-size: 16px; font-weight: 700; color: #1a1a2e;
                       margin: 28px 0 12px; display: flex; align-items: center; gap: 10px; }}
    .section-header .count {{ background: #e8eaf6; color: #3949ab; font-size: 12px;
                               font-weight: 700; padding: 2px 10px; border-radius: 12px; }}
    .section-sub {{ font-size: 12px; font-weight: 400; color: #888; }}
    .section-header.other-header {{ color: #b45309; }}
    .section-header.other-header .count {{ background: #fef3c7; color: #b45309; }}
    .section-header.resolved-header {{ color: #555; }}
    .section-header.resolved-header .count {{ background: #f5f5f5; color: #777; }}
    .table-wrap {{ overflow-x: auto; background: white; border-radius: 10px;
                   box-shadow: 0 2px 12px rgba(0,0,0,0.08); margin-bottom: 8px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    thead th {{ background: #1a1a2e; color: white; padding: 12px 14px;
                text-align: left; font-size: 12px; font-weight: 600;
                letter-spacing: 0.04em; white-space: nowrap; position: sticky; top: 0;
                cursor: pointer; user-select: none; }}
    thead th:hover {{ background: #2d3a5e; }}
    .sort-icon {{ opacity: 0.5; font-size: 10px; }}
    thead th.sort-asc .sort-icon::after {{ content: " ▲"; opacity: 1; }}
    thead th.sort-desc .sort-icon::after {{ content: " ▼"; opacity: 1; }}
    thead th.sort-asc .sort-icon, thead th.sort-desc .sort-icon {{ opacity: 1; }}
    tbody tr {{ border-bottom: 1px solid #f0f0f0; transition: background 0.15s; }}
    tbody tr:hover {{ background: #f0f4ff; }}
    tbody tr:last-child {{ border-bottom: none; }}
    td {{ padding: 10px 14px; vertical-align: middle; }}
    .key-link {{ color: #0052cc; font-weight: 600; text-decoration: none;
                 white-space: nowrap; }}
    .key-link:hover {{ text-decoration: underline; }}
    .summary-cell {{ max-width: 380px; word-break: break-word; overflow-wrap: break-word; }}
    .badge {{ color: white; padding: 3px 9px; border-radius: 12px;
              font-size: 11px; font-weight: 600; white-space: nowrap; }}
    .priority {{ font-size: 12px; color: #c62828; font-weight: 600; }}
    .age {{ color: #777; font-size: 12px; white-space: nowrap; }}
    .search-bar {{ margin-bottom: 16px; }}
    .search-bar input {{ width: 100%; max-width: 400px; padding: 8px 14px;
                         border: 1px solid #ddd; border-radius: 6px;
                         font-size: 13px; outline: none; }}
    .search-bar input:focus {{ border-color: #0052cc; box-shadow: 0 0 0 2px #cce0ff; }}
    .diff-banner {{ background: white; border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,0.08);
                    margin-bottom: 24px; overflow: hidden; }}
    .diff-banner.diff-none {{ padding: 12px 20px; color: #888; font-size: 13px; font-style: italic; }}
    .diff-header {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
                    padding: 14px 20px; background: #f8f9ff; border-bottom: 1px solid #e8eaf6; }}
    .diff-title {{ font-size: 15px; font-weight: 700; color: #1a1a2e; }}
    .diff-meta {{ font-size: 12px; color: #888; }}
    .diff-delta {{ font-size: 14px; font-weight: 700; margin-left: auto; }}
    .diff-pills {{ display: flex; gap: 6px; }}
    .diff-pill {{ font-size: 11px; font-weight: 700; padding: 2px 9px; border-radius: 10px; }}
    .diff-pill.new {{ background: #e8f5e9; color: #2e7d32; }}
    .diff-pill.removed {{ background: #ffebee; color: #c62828; }}
    .diff-pill.changed {{ background: #fff3e0; color: #e65100; }}
    .diff-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    .diff-table th {{ background: #f0f0f0; color: #555; padding: 8px 16px;
                      text-align: left; font-size: 11px; font-weight: 600; }}
    .diff-table td {{ padding: 8px 16px; border-bottom: 1px solid #f5f5f5; vertical-align: middle; }}
    .diff-new td {{ background: #f9fff9; }}
    .diff-removed td {{ background: #fff9f9; }}
    .diff-changed td {{ background: #fffdf5; }}
    .diff-from {{ color: #999; text-decoration: line-through; }}
    .diff-to {{ color: #1e88e5; font-weight: 600; }}
    .diff-nochange {{ padding: 12px 20px; color: #888; font-size: 13px; font-style: italic; margin: 0; }}
    .pr-cell {{ min-width: 180px; }}
    .pr-list {{ display: flex; flex-direction: column; gap: 4px; }}
    .pr-link {{ display: inline-flex; align-items: center; gap: 5px; font-size: 11px;
                font-weight: 600; text-decoration: none; padding: 2px 8px 2px 6px;
                border-radius: 10px; border: 1.5px solid; white-space: nowrap;
                max-width: 220px; overflow: hidden; text-overflow: ellipsis; }}
    .pr-link:hover {{ opacity: 0.8; text-decoration: underline; }}
    .pr-status-dot {{ width: 7px; height: 7px; border-radius: 50%;
                      flex-shrink: 0; display: inline-block; }}
    footer {{ text-align: center; color: #aaa; font-size: 11px; padding: 24px; }}
  </style>
</head>
<body>
  <header>
    <h1>Mainline Blockers — {escape_html(version)}</h1>
    <div class="meta">Generated: {today} &nbsp;|&nbsp;
      <a href="{JIRA_BASE_URL}/jira/software/c/projects/ROCM/summary"
         style="color:#7eb8f7" target="_blank">ROCM Project ↗</a>
    </div>
  </header>
  <div class="jql-bar">{escape_html(jql)}</div>
  <div class="container">
    {build_diff_html(diff)}
    <div class="summary-bar">
      {summary_pills}
      <span class="total">Total: <strong>{len(issues)}</strong> tickets</span>
    </div>
    <div class="search-bar">
      <input type="text" id="search" placeholder="Filter by key, summary, assignee..."
             oninput="filterTables(this.value)">
    </div>

    <div class="section-header">
      Active Blockers <span class="section-sub">P1 + S1</span>
      <span class="count">{len(primary_blockers)}</span>
    </div>
    {primary_table}

    <div class="section-header other-header">
      Other High Priority <span class="section-sub">P1 + S2 &nbsp;/&nbsp; P2 + S1</span>
      <span class="count">{len(other_high)}</span>
    </div>
    {other_table}

    <div class="section-header resolved-header">
      Resolved (Done / Discarded)
      <span class="count">{len(resolved)}</span>
    </div>
    {resolved_table}
  </div>
  <footer>ROCm TPM Workspace &nbsp;·&nbsp; Data from Jira ROCM project</footer>
  <script>
    function filterTables(q) {{
      q = q.toLowerCase();
      document.querySelectorAll('tbody tr').forEach(row => {{
        row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
      }});
    }}

    const sortState = {{}};
    function parseAge(s) {{
      const m = s.match(/(\\d+)d ago/);
      if (m) return parseInt(m[1], 10);
      if (s === 'today') return 0;
      return -1;
    }}
    const ageCols = new Set([11, 12]);
    function sortTable(tableId, colIdx) {{
      const table = document.getElementById(tableId);
      const tbody = table.querySelector('tbody');
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const ths = table.querySelectorAll('thead th');
      const key = tableId + ':' + colIdx;
      const asc = sortState[key] !== true;
      sortState[key] = asc;

      ths.forEach((th, i) => {{
        th.classList.remove('sort-asc', 'sort-desc');
        if (i === colIdx) th.classList.add(asc ? 'sort-asc' : 'sort-desc');
      }});

      rows.sort((a, b) => {{
        const ta = a.cells[colIdx]?.textContent.trim().toLowerCase() ?? '';
        const tb = b.cells[colIdx]?.textContent.trim().toLowerCase() ?? '';
        if (ageCols.has(colIdx)) {{
          const na = parseAge(ta), nb = parseAge(tb);
          if (na >= 0 && nb >= 0) return asc ? na - nb : nb - na;
        }}
        return asc ? ta.localeCompare(tb) : tb.localeCompare(ta);
      }});
      rows.forEach(r => tbody.appendChild(r));
    }}
  </script>
</body>
</html>"""


def build_markdown(issues: list[dict], version: str, jql: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"# Jira P1/S1 Tickets — {version}",
        f"_Generated: {today}_",
        f"_JQL: `{jql}`_",
        f"_Total: {len(issues)} issues_",
        "",
        "---",
        "",
    ]

    if not issues:
        lines.append("No P1/S1 issues found for this version.")
        return "\n".join(lines)

    lines += [
        "| Key | Summary | Status | Assignee | Reporter | Updated |",
        "|-----|---------|--------|----------|----------|---------|",
    ]

    for issue in issues:
        key = issue.get("key", "?")
        url = f"{JIRA_BASE_URL}/browse/{key}"
        summary = safe_field(issue, "fields", "summary")
        if len(summary) > 70:
            summary = summary[:67] + "..."
        status = safe_field(issue, "fields", "status", "name")
        assignee = safe_field(issue, "fields", "assignee", "displayName")
        reporter = safe_field(issue, "fields", "reporter", "displayName")
        updated = format_age(safe_field(issue, "fields", "updated", default=""))
        lines.append(f"| [{key}]({url}) | {summary} | {status} | {assignee} | {reporter} | {updated} |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch P1 Jira tickets for a ROCm version and generate a report."
    )
    parser.add_argument(
        "--version", default="ROCm 7.13.0",
        help="Affects Version value to filter on (default: 'ROCm 7.13.0')"
    )
    parser.add_argument(
        "--html", action="store_true",
        help="Generate an HTML report and open it in the browser"
    )
    parser.add_argument(
        "--save", action="store_true",
        help="Save the report to reports/ directory"
    )
    parser.add_argument(
        "--json", action="store_true", dest="output_json",
        help="Output raw JSON instead of a report"
    )
    parser.add_argument(
        "--all-p1", action="store_true",
        help="Include all P1 tickets regardless of severity"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the JQL query that would be used, then exit"
    )
    args = parser.parse_args()

    if args.all_p1:
        jql = (
            f'project = ROCM '
            f'AND affectedVersion = "{args.version}" '
            f'AND priority in ("P1: High", "P1 (Gating)") '
            f'ORDER BY updated DESC'
        )
    else:
        jql = (
            f'project = ROCM '
            f'AND affectedVersion = "{args.version}" '
            f'AND ('
            f'  priority in ("P1: High", "P1 (Gating)")'
            f'  OR (priority = "P2: Medium" AND cf[10417] = "S1: Critical")'
            f') '
            f'ORDER BY updated DESC'
        )

    if args.dry_run:
        print(f"JQL: {jql}")
        print(f"URL: {JIRA_BASE_URL}/rest/api/3/search/jql")
        print("(dry-run: no request made)")
        return

    auth_header = get_auth_header()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    fields = [
        "summary", "status", "priority", "assignee", "reporter",
        "created", "updated", "duedate", "components",
        "fixVersions", "affectedVersions",
        "customfield_10047",   # Severity
        "customfield_10417",   # Assessed Severity
        "customfield_11403",   # Triage Assignment
        "customfield_11214",   # Customer(s)
    ]

    print(f"Fetching P1 tickets for '{args.version}' from {JIRA_BASE_URL}...", file=sys.stderr)
    issues = jira_search(auth_header, jql, fields)
    print(f"Found {len(issues)} issues.", file=sys.stderr)

    if args.output_json:
        print(json.dumps(issues, indent=2))
        return

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d-%H%M")
    version_slug = args.version.lower().replace(" ", "-").replace(".", "")
    reports_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "reports"))

    # Snapshot + diff
    curr_snapshot = snapshot_from_issues(issues, args.version, timestamp)
    prev_snapshot = load_previous_snapshot(reports_dir, version_slug, timestamp)
    diff = compute_diff(prev_snapshot, curr_snapshot) if prev_snapshot else None
    if diff:
        print_diff(diff)
    else:
        print("No previous snapshot found — skipping diff.", file=sys.stderr)
    save_snapshot(curr_snapshot, reports_dir, timestamp, version_slug)

    if args.html:
        html = build_html(issues, args.version, jql, auth_header, diff)
        if args.save:
            out_path = os.path.join(reports_dir, f"{timestamp}-mainline-blockers-{version_slug}.html")
            out_path = os.path.normpath(out_path)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"Saved to: {out_path}", file=sys.stderr)
            webbrowser.open(f"file:///{out_path.replace(os.sep, '/')}")
        else:
            # Write to a temp file and open
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".html", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(html)
                tmp_path = tmp.name
            webbrowser.open(f"file:///{tmp_path.replace(os.sep, '/')}")
            print(f"Opened in browser: {tmp_path}", file=sys.stderr)
    else:
        report = build_markdown(issues, args.version, jql)
        print(report)
        if args.save:
            out_path = os.path.join(reports_dir, f"{timestamp}-mainline-blockers-{version_slug}.md")
            out_path = os.path.normpath(out_path)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"\nSaved to: {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
