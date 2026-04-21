# ROCm TPM Workspace

This workspace is for TPM/Manager oversight of the ROCm ecosystem — focused on Jira ticket tracking, escalation, and stakeholder reporting.

## Purpose

- Fetch and report P1 mainline blocker tickets from Jira
- Track open issues against specific ROCm releases
- Generate dated reports for stakeholder visibility

## Key Directories

| Path | Description |
|------|-------------|
| `reports/` | Generated reports (dated markdown files) |
| `scripts/` | Python scripts for Jira and GitHub operations |
| `.claude/commands/` | Slash command definitions |

## Slash Commands

| Command | Purpose |
|---------|---------|
| `/mainline-blocker` | Fetch P1 blocker tickets from Jira ROCM project (auto-detects latest version from TheRock releases) |
| `/mainline-blocker <version>` | Fetch P1 blockers for a specific version (e.g. `ROCm 7.12.0`) |

### How `/mainline-blocker` Works

1. Reads `JIRA_API_TOKEN` and `JIRA_EMAIL` from `.env` file or environment variables
2. Calls `scripts/jira_p1s1.py` via Bash
3. Queries the [ROCM Jira project](https://amd-hub.atlassian.net/jira/software/c/projects/ROCM/summary) using the Jira REST API v3
4. Filters: `P1` tickets + `P2` tickets with Assessed Severity = `S1: Critical`
5. Displays formatted markdown report and offers to save it

### Setup

**Option A — `.env` file (recommended, one-time):**
Run the script once to auto-create a blank `.env`, then fill in your credentials. The script auto-loads from this file.

**Option B — Environment variables (per session):**

PowerShell: `$env:JIRA_API_TOKEN = "your_token"` / `$env:JIRA_EMAIL = "your.email@amd.com"`
Bash: `export JIRA_API_TOKEN="your_token"` / `export JIRA_EMAIL="your.email@amd.com"`

> Generate your token at: https://id.atlassian.com/manage-profile/security/api-tokens

## Utility Scripts

### `scripts/jira_p1s1.py` — Jira P1 Blocker Fetcher

Fetches P1 tickets from the ROCM Jira project with affectedVersion filter.

```bash
# Open results in browser (HTML dashboard)
python scripts/jira_p1s1.py --version "ROCm 7.13.0" --html

# Open in browser AND save HTML to reports/
python scripts/jira_p1s1.py --version "ROCm 7.13.0" --html --save

# Markdown output (default)
python scripts/jira_p1s1.py --version "ROCm 7.13.0"

# Save markdown to reports/
python scripts/jira_p1s1.py --version "ROCm 7.13.0" --save

# All P1 regardless of severity
python scripts/jira_p1s1.py --version "ROCm 7.13.0" --all-p1

# Preview JQL without making a request
python scripts/jira_p1s1.py --dry-run

# Raw JSON output
python scripts/jira_p1s1.py --json
```

**Auth:** Reads `JIRA_API_TOKEN` and `JIRA_EMAIL` from environment. Never pass tokens as CLI arguments.

**Jira field reference:**
- Project: `ROCM`
- Priority field: `priority` — values: `P1: High`, `P1 (Gating)`, `P2: Medium`
- Severity field: `customfield_10047` — values: `Critical`, `Blocker`, `Major`, etc. (legacy, fetched but not used in default JQL filter)
- Assessed Severity field: `customfield_10417` — values: `S1: Critical`, `S2: Major`, etc. (used in default JQL filter and HTML column)
- Triage Assignment field: `customfield_11403` — multi-select, displayed in HTML dashboard
- Customer(s) field: `customfield_11214` — displayed in HTML dashboard
- Affects Version: `affectedVersion`

## Formatting Rules

**All Jira and GitHub references must be fully hyperlinked in reports.**

- Jira: `[ROCM-12345](https://amd-hub.atlassian.net/browse/ROCM-12345)`
- GitHub PRs: `[TheRock#123](https://github.com/ROCm/TheRock/pull/123)`
- Never use bare ticket numbers like `#12345` or `ROCM-12345` without a link

## Notes

- Reports saved as `reports/YYYY-MM-DD-<slug>.md`
- `JIRA_API_TOKEN` must never be committed or passed as a CLI argument — environment variables only
- Jira REST API v3 endpoint: `https://amd-hub.atlassian.net/rest/api/3/search/jql`
- Pagination uses `nextPageToken` (not `startAt`) in API v3
