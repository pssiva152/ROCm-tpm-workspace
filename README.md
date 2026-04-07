# ROCm TPM Workspace

A Claude Code workspace for TPM/Manager oversight of the ROCm ecosystem. Focused on tracking P1 mainline blocker tickets from Jira and generating stakeholder reports.

## Prerequisites

### 1. Install Claude Code

Follow the [Claude Code installation guide](https://docs.anthropic.com/en/docs/claude-code/overview) or your organization's internal setup instructions.

### 2. Python 3.10+

The helper scripts require Python 3.10 or later:

```powershell
python --version
```

### 3. Jira Access Token

Generate an API token from your Atlassian account:

> https://id.atlassian.com/manage-profile/security/api-tokens

#### Option A — `.env` file (recommended)

Run the script once — it auto-creates a blank `.env` file in the project root:

```powershell
python scripts/jira_p1s1.py --dry-run
```

Then edit `.env` with your token and email:

```
JIRA_API_TOKEN=your_token_here
JIRA_EMAIL=your_email@amd.com
```

> `.env` is gitignored — your credentials will never be pushed, even if you commit everything.
> The script auto-loads from this file. No export needed.

#### Option B — Permanent environment variables

Set the variables once so they persist across all sessions and VS Code restarts:

```powershell
[Environment]::SetEnvironmentVariable("JIRA_API_TOKEN", "your_token_here", "User")
[Environment]::SetEnvironmentVariable("JIRA_EMAIL", "your_email@amd.com", "User")
```

> After running these commands, **fully restart VS Code** for the variables to take effect.
> You only need to do this once — they survive reboots.

#### Option C — Session only

Set them each time you open a terminal (lost when the terminal closes):

**PowerShell:**
```powershell
$env:JIRA_API_TOKEN = "your_token_here"
$env:JIRA_EMAIL    = "your_email@amd.com"
```

**Bash/zsh:**
```bash
export JIRA_API_TOKEN="your_token_here"
export JIRA_EMAIL="your_email@amd.com"
```

> **Note:** If using the Claude Code VS Code extension, only Option A or B work reliably.
> The extension's internal shell is bash — PowerShell session variables set after VS Code launches
> are not visible to it.

## Usage

### Slash Command

Type directly in the Claude Code chat:

| Command | What it does |
|---------|-------------|
| `/mainline-blocker` | Fetch tickets for ROCm 7.13.0, open HTML dashboard in browser |
| `/mainline-blocker ROCm 7.12.0` | Fetch tickets for a specific version |

### Example Workflow

```
1. Set credentials permanently (Option A above) and restart VS Code
2. Open this workspace in VS Code with the Claude Code extension
3. Type: /mainline-blocker
4. Browser opens with the HTML dashboard
5. Claude also displays a formatted summary in chat
6. Optionally save the report when prompted
```

## HTML Dashboard

The `/mainline-blocker` command opens an interactive browser dashboard with:

- **Three sections:**
  - **Active Blockers** — P1 priority + S1 (Critical) assessed severity
  - **Other High Priority** — P1 + S2, or P2 + S1
  - **Resolved (Done / Discarded)** — closed tickets for reference

- **Columns:**
  | Column | Source |
  |--------|--------|
  | Key | Jira ticket key (linked) |
  | Summary | Ticket title |
  | Status | Color-coded badge (Open, In Progress, Validate, etc.) |
  | Priority | P1 / P2 |
  | Assessed Severity | S1: Critical, S2: Major, etc. |
  | Triage Assignment | Team/area assigned for triage |
  | Due Date | Target resolution date |
  | Customer(s) | Affected customers if set |
  | Assignee | Current owner |
  | Reporter | Who filed the ticket |
  | PR(s) | Linked GitHub PRs with status (Open / Merged / Declined) |
  | Updated | Days since last update |
  | Created | Ticket age |

- **Sortable headers** — click any column to sort ascending/descending
- **Live search** — filter across all sections by key, summary, assignee, etc.
- **Changes Since Last Report** — diff banner at the top comparing against the previous run (see below)

## Diff / Change Tracking

Every run automatically saves a JSON snapshot to `reports/`. On subsequent runs, the script compares the current results against the most recent snapshot for the same version and reports what changed.

### Terminal output

```
============================================================
  Changes vs last report (2026-04-06-0900)
  Total: 57 → 60  ▲ +3
============================================================
  NEW tickets (3):
    + ROCM-21300  [Open]  Some new blocker...  https://amd-hub.atlassian.net/browse/ROCM-21300
  STATUS changes (2):
    ~ ROCM-21042  In Progress → Done
    ~ ROCM-21271  Triage → In Progress
============================================================
```

### HTML banner

The browser dashboard shows a **Changes Since Last Report** banner above the tables with:
- Total ticket count delta (▲ increased / ▼ decreased)
- Color-coded pills: **green** = new tickets, **red** = removed tickets, **amber** = status changes
- A detail table listing every added, removed, or status-changed ticket

### Snapshot files

| File | Purpose |
|------|---------|
| `reports/{timestamp}-mainline-blockers-{version}.json` | Auto-saved on every run — used for diffing |
| `reports/{timestamp}-mainline-blockers-{version}.html` | Saved only when `--save` flag is passed |
| `reports/{timestamp}-mainline-blockers-{version}.md` | Saved only when `--save` flag is passed |

The first run for a new version will show "No previous snapshot found" — the diff starts working from the second run onward.

## Helper Script

### `scripts/jira_p1s1.py`

Fetches tickets from the [ROCM Jira project](https://amd-hub.atlassian.net/jira/software/c/projects/ROCM/summary) via the Jira REST API v3.

```powershell
# Open HTML dashboard in browser (recommended)
python scripts/jira_p1s1.py --version "ROCm 7.13.0" --html

# Open in browser AND save HTML to reports/
python scripts/jira_p1s1.py --version "ROCm 7.13.0" --html --save

# Markdown output in terminal
python scripts/jira_p1s1.py --version "ROCm 7.13.0"

# Save markdown to reports/
python scripts/jira_p1s1.py --version "ROCm 7.13.0" --save

# All P1 tickets regardless of severity
python scripts/jira_p1s1.py --version "ROCm 7.13.0" --all-p1

# Preview the JQL query without making a request
python scripts/jira_p1s1.py --dry-run

# Raw JSON output
python scripts/jira_p1s1.py --json
```

**Default filter logic:**
- P1 tickets (`P1: High` or `P1 (Gating)`) **plus** P2 tickets where Assessed Severity = S1
- Includes linked GitHub PR data (status, link) via Jira dev-status API

**Auth:** Reads `JIRA_API_TOKEN` and `JIRA_EMAIL` from environment variables only. Never pass tokens as CLI arguments.

## Reports

Reports are saved to `reports/`:

- `reports/YYYY-MM-DD-mainline-blockers-<version>.html` — HTML dashboard snapshot
- `reports/YYYY-MM-DD-mainline-blockers-<version>.md` — Markdown report for sharing

## Configuration

| File | Purpose |
|------|---------|
| `CLAUDE.md` | System prompt with Jira field references, formatting rules, script docs |
| `.claude/commands/mainline-blocker.md` | Defines the `/mainline-blocker` slash command behavior |
| `.claude/settings.json` | Workspace-level permissions for Claude Code |

## Architecture

1. `.claude/commands/mainline-blocker.md` defines what Claude does when `/mainline-blocker` is invoked
2. `CLAUDE.md` acts as a system prompt with domain knowledge and Jira field references
3. `scripts/jira_p1s1.py` handles all Jira API access (REST API v3, Basic auth, dev-status API for PRs)
4. Reports are saved to `reports/` for sharing and record-keeping
