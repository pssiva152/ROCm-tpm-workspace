---
description: Fetch P1 mainline blocker tickets from Jira ROCM project for a given ROCm version
allowed-tools: Bash, Write
---

# Mainline Blockers

Fetch P1 tickets (all priorities) plus P2 tickets with Assessed Severity = S1: Critical, from the Jira ROCM project for a given ROCm version.

## IMPORTANT RULES

- NEVER modify, edit, or fix the Python script or any other source files
- NEVER create git commits or push changes
- If the script fails or shows a setup message, relay the message to the user and STOP

## Instructions

### 0. Check Auth

Run a quick dry-run to verify credentials are available (either from `.env` file or environment variables):

```bash
python scripts/jira_p1s1.py --dry-run
```

If the script exits with a "FIRST-TIME SETUP" or "credentials are missing" message, show the user:
- A `.env` file has been created (or needs to be filled in) at the project root
- They need to add their `JIRA_API_TOKEN` and `JIRA_EMAIL` to that file
- See `README.md` for detailed instructions

Do NOT proceed if the dry-run fails. Do NOT try to fix the problem.

### 1. Determine Target Version

Check if the user specified a version in the command (e.g. `/mainline-blocker ROCm 7.13.0`).

If not specified, fetch the latest release tag from GitHub to determine the default version:

```bash
python -c "
import urllib.request, json, re, sys
try:
    req = urllib.request.Request('https://api.github.com/repos/ROCm/TheRock/releases/latest', headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=5) as r:
        tag = json.load(r).get('tag_name', '')
    m = re.search(r'(\d+\.\d+(?:\.\d+)?)', tag)
    print('ROCm ' + m.group(1) if m else '', end='')
except Exception as e:
    print('', end='')
"
```

- If the command returns a version (e.g. `ROCm 7.13.0`), use it as the default and inform the user it was auto-detected from [TheRock releases](https://github.com/ROCm/TheRock/releases).
- If the command returns empty or fails, fall back to **ROCm 7.13.0** and note that the GitHub fetch failed.

### 2. Fetch Tickets

Run the script with the target version (either user-specified or auto-detected in step 1). ALWAYS use `--html --save --no-open` to silently save the HTML dashboard without opening the browser:

```bash
python scripts/jira_p1s1.py --version "<RESOLVED_VERSION>" --html --save --no-open
```

Replace `<RESOLVED_VERSION>` with the version determined in step 1.

NEVER run the script more than once per command invocation. One run does everything — fetch and save.

The script fetches from the ROCM Jira project:
- **P1 tickets**: priority = `P1: High` or `P1 (Gating)` (all severities)
- **P2 + S1 tickets**: priority = `P2: Medium` AND Assessed Severity = `S1: Critical`

> **Note on severity**: The ROCM project often leaves the Assessed Severity field blank on P1 tickets.
> The default query fetches all P1 tickets regardless of severity, plus P2 tickets only if they have S1: Critical assessed severity.

### 3. If 0 Results with Severity Filter

If the script returns 0 results, run a broader query without the severity filter:

```bash
python scripts/jira_p1s1.py --version "<RESOLVED_VERSION>" --all-p1
```

Then note in the report: "No tickets had Severity explicitly set to Critical/Blocker. Showing all P1 tickets."

### 4. Generate Report

The script outputs a structured markdown summary to stdout. Use that data to format the chat report as follows:

```markdown
# Mainline Blockers — ROCm [VERSION]

_Generated: [DATE]_
_Source: [Jira ROCM project](https://amd-hub.atlassian.net/jira/software/c/projects/ROCM/summary)_

## Summary

| Category | Count |
|----------|-------|
| Total tickets | N |
| Active P1+S1 blockers | N |
| Other high priority (P1+S2 / P2+S1) | N |
| Resolved (Done / Discarded) | N |

## Active Blockers — P1 + S1 (N)

Notable items requiring attention:
- [bullet points highlighting key concerns — e.g., unassigned tickets, tickets stuck in Triage/Queue, oldest tickets]

| Key | Summary | Status | Assignee | Updated |
|-----|---------|--------|----------|---------|
| [ROCM-XXXXX](link) | Summary | Status | Name | Nd ago |

## Other High Priority — P1+S2 / P2+S1 (N)

Notable items requiring attention:
- [bullet points highlighting key concerns — e.g., new tickets today, performance regressions, security issues]

| Key | Summary | Status | Assignee | Updated |
|-----|---------|--------|----------|---------|
| [ROCM-XXXXX](link) | Summary | Status | Name | Nd ago |

## Recently Resolved (N)

[brief summary — e.g., "3 resolved today: ROCM-XXXXX (Done), ROCM-YYYYY (Discarded)"]

---

**Full interactive dashboard saved to:** [reports/YYYY-MM-DD-HHMM-mainline-blockers-version.html](reports/YYYY-MM-DD-HHMM-mainline-blockers-version.html)
```

Read the saved HTML path from the script's stderr output (line starting with "Saved HTML to:") and use it for the link at the end.

## Notes

- Exclude tickets in **Done** or **Discarded** status from the active sections (show them in the Resolved section)
- Always link ticket keys to `https://amd-hub.atlassian.net/browse/ROCM-XXXXX`
- If the Severity field is blank, note it as "Severity not set" rather than hiding the ticket
- Age = days since `updatedAt`
- NEVER open the browser yourself — the user will click the dashboard link if they want it
