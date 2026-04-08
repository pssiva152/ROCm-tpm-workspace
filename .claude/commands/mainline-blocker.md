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
If not, default to **ROCm 7.13.0** and inform the user.

### 2. Fetch Tickets

Run the script with the target version. ALWAYS use `--html --save` to open the dashboard in the browser AND save it to `reports/` in a single run:

```bash
python scripts/jira_p1s1.py --version "ROCm 7.13.0" --html --save
```

Replace `ROCm 7.13.0` with the user-specified version if provided.

NEVER run the script more than once per command invocation. One run does everything — fetch, display, and save.

The script fetches from the ROCM Jira project:
- **P1 tickets**: priority = `P1: High` or `P1 (Gating)` (all severities)
- **P2 + S1 tickets**: priority = `P2: Medium` AND Assessed Severity = `S1: Critical`

> **Note on severity**: The ROCM project often leaves the Assessed Severity field blank on P1 tickets.
> The default query fetches all P1 tickets regardless of severity, plus P2 tickets only if they have S1: Critical assessed severity.

### 3. If 0 Results with Severity Filter

If the script returns 0 results, run a broader query without the severity filter:

```bash
python scripts/jira_p1s1.py --version "ROCm 7.13.0" --all-p1
```

Then note in the report: "No tickets had Severity explicitly set to Critical/Blocker. Showing all P1 tickets."

### 4. Generate Report

Format the output as:

```markdown
# Mainline Blockers — ROCm [VERSION]

_Generated: [DATE]_
_Source: [Jira ROCM project](https://amd-hub.atlassian.net/jira/software/c/projects/ROCM/summary)_

## Summary
- **Total P1 blockers**: N
- **Open / In Progress**: N
- **Awaiting triage**: N
- **Done / Discarded**: N (excluded below)

## Active Blockers (Open / In Progress / Triage / Queue)

| Key | Summary | Status | Assignee | Age |
|-----|---------|--------|----------|-----|
| [ROCM-XXXXX](link) | Summary | Status | @name | Nd |

## Needs Triage

PRs in Triage state with no assignee — need owner assignment.

## Recently Resolved (last 7 days)

| Key | Summary | Resolution |
|-----|---------|------------|
```

## Notes

- Exclude tickets in **Done** or **Discarded** status from the active section (show them in a separate "Resolved" section)
- Always link ticket keys to `https://amd-hub.atlassian.net/browse/ROCM-XXXXX`
- If the Severity field is blank, note it as "Severity not set" rather than hiding the ticket
- Age = days since `updatedAt`
