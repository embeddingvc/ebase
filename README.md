# LinkedIn Outreach

Automation and workflow tooling for LinkedIn outreach: a Python project with a **LinkedIn MCP server** (`tools/server.py`) that Claude can call for browser actions and filesystem-backed pipeline state under `outreach/`.

## Architecture
```mermaid
%% LinkedIn Outreach — High-Level Overview
%% Architecture + 5-step sequence + exit conditions

flowchart TB

%% ─────────────────────────────────
%% ARCHITECTURE LAYERS
%% ─────────────────────────────────

subgraph ARCH ["System Architecture"]
  direction LR
  L1["Claude + Skills\nOrchestration layer\nReads SKILL.md instructions\nComposes messages"]
  L2["MCP Server\nFastMCP · Python\n20+ tools exposed\nAbstracts all I/O"]
  L3["Playwright\nChrome via CDP\nHuman-like delays\nStealth mode"]
  L4["LinkedIn\nProfiles · DMs\nConnection requests\nFeed · Posts"]
  L1 -- "tool calls" --> L2
  L2 -- "browser automation" --> L3
  L3 -- "HTTP / DOM" --> L4
end

%% ─────────────────────────────────
%% DATA LAYER
%% ─────────────────────────────────

subgraph DATA ["Persistence (via MCP filesystem tools)"]
  direction LR
  D1["prospects/\nOne JSON per prospect\nProfile · stage · notes"]
  D2["conversations/\nOne JSON per thread\nMessages · state machine\nplanned_message"]
  D3["connections.json\nMaster registry\nstatus · timestamps"]
  D4["logs/\nactions.jsonl\nplanned_messages.jsonl\nFull audit trail"]
  D5["storage/reports/\nEnd-of-sequence\nmarkdown reports"]
end
```

## Prerequisites

- **Python** 3.10 or newer  
- **[uv](https://docs.astral.sh/uv/)** (recommended) for environments and `uv run`  
- **Google Chrome** (live mode): used with remote debugging so Playwright can attach  
- **Claude** desktop app with **Cowork** (or another MCP host that supports stdio MCP servers)
- **Make** (for `make install`, `make browser`, etc.)

### macOS: Install Make

Apple ships **GNU Make** with the Xcode Command Line Tools. If `make --version` fails in Terminal:

1. Run:

   ```bash
   xcode-select --install
   ```

2. Complete the installer dialog, then confirm:

   ```bash
   make --version
   ```

You can still use **`uv`** commands everywhere if you prefer not to install the Command Line Tools; `make` is only a convenience wrapper around those commands.

## Install the project

From the repository root (this should create uv venv and install chromium):

```bash
make install
```

## Claude Cowork

Cowork is the task-oriented workspace in the Claude desktop app. It can use **MCP tools** (including this repo’s LinkedIn server) the same way other Claude surfaces do, as long as the server is registered in your app config.

Optional **preferences** (example in [`claude_desktop_config.json`](claude_desktop_config.json)):

- `coworkScheduledTasksEnabled` — scheduled tasks in Cowork  
- `coworkWebSearchEnabled` — web search in Cowork  
- `sidebarMode` — e.g. `"task"` for task-focused sidebar  
- `ccdScheduledTasksEnabled` — scheduled tasks for Claude Code Desktop integration, if you use it  

Merge any keys you want into your **user** Claude config (see below). Do not commit secrets or machine-specific paths.

## Installing skills

Workflow instructions for Claude live in **`outreach/skills/`**. Each skill is its **own directory** with a **`SKILL.md`** file. Those skills assume the **LinkedIn MCP server** is available (see [MCP setup](#mcp-setup)).

**Core skills (this repo):** `conversation-planner`, `send-connection-request`, `sync-pending-connections` — each under `outreach/skills/<name>/`.

### Claude
1. `Customize` → `Skills` → `+` → `Create skill` → `Upload a skill`
2. Select the `SKILL.md` files under `outreach/skills/`
3. Repeat for `conversation-planner`, `send-connection-request`, and `sync-pending-connections`

## MCP setup

### Claude
1. `Settings` → `Developer` → `Edit Config`
   - That opens `claude_desktop_config.json`.
   - On macOS the file usually lives at: `~/Library/Application Support/Claude/claude_desktop_config.json`
2. Register the LinkedIn MCP server
   - Replace the placeholders with your `uv` binary path (`which uv`).
   - Replace the placeholders with your `repo` path (`pwd`)
```json
{
  "mcpServers": {
    "linkedin": {
      "command": "/absolute/path/to/uv",
      "args": [
        "run",
        "--project",
        "/absolute/path/to/LinkedIn-Outreach",
        "/absolute/path/to/LinkedIn-Outreach/tools/server.py"
      ]
    }
  }
}
```

If you already have other MCP servers, merge the `"linkedin"` block into the existing `mcpServers` object instead of replacing the whole file.

The sample in [`claude_desktop_config.json`](claude_desktop_config.json) matches this shape; update every path to match your machine.

## Last Steps:
1. Start Chrome with debugging (from the repo root):

   ```bash
   make browser
   ```

2. Sign in to LinkedIn in that Chrome window.

3. Use Cowork / Claude with the MCP tools as usual.

If Chrome is not running with remote debugging, live tools will fail until `make browser` (or an equivalent launch) is used.

### Example Usage
1. Connect to <linkedin-url>.
2. Is <linkedin-url> my connection?
3. Add `Run conversation planner skill` as a scheduled task.

### Mock mode (optional, no browser)

For scripted tests without a browser, `tools/server.py` can run in mock mode when `_mock_mcp_enabled()` returns `True` (see the top of that file). In mock mode, tools use `tools/mock.py` instead of Playwright.

---

Reference Makefile targets: `make help` (browser, worker, tests, logs).

## Detailed Workflow Diagram
```mermaid
%% LinkedIn outreach — detailed flow (vertical layout)
%% Main axis: top → bottom; nested subgraphs use TB where possible

flowchart TB
  %% ─── Aesthetic & roles ───
  classDef gate fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px,color:#1b5e20
  classDef step fill:#e3f2fd,stroke:#0d47a1,stroke-width:1.5px,color:#0d1b2a
  classDef decision fill:#fff8e1,stroke:#e65100,stroke-width:1.5px,color:#4e342e
  classDef terminal fill:#fce4ec,stroke:#880e4f,stroke-width:1.5px,color:#4a148c
  classDef phase fill:#f3e5f5,stroke:#6a1b9a,stroke-width:1.5px,color:#311b92
  classDef batch fill:#eceff1,stroke:#37474f,stroke-width:1.5px,color:#263238

  START(["Start outreach"]):::gate
  START --> DISCOVER

  DISCOVER["① Discover prospect<br/>• Skill: scrape-profile · MCP: scrape_profile<br/>• Playwright collects public profile fields<br/>• Write prospect.json · stage: cold"]:::step

  DISCOVER --> ROUTE{"Already 1st degree?"}:::decision
  ROUTE -->|No · 2nd / 3rd| CONNECT
  ROUTE -->|Yes| ENGAGE

  CONNECT["② Send connection request<br/>• Skill: send-connection-request<br/>• Personal note ≤ 300 chars · MCP: send_connection_request<br/>• Playwright: Connect → Add note → Send<br/>• Persist · stage: pending_connection"]:::step

  CONNECT --> WAIT

  WAIT["③ Wait for acceptance<br/>• Skill: sync-pending-connections<br/>• MCP: is_first_degree_connection<br/>• Playwright verifies connection state / badge"]:::step

  WAIT --> ACC{"Accepted?"}:::decision
  ACC -->|No · &gt; 48h| DEAD
  ACC -->|Yes| ENGAGE

  DEAD["Mark prospect dead<br/>ended_reason: no_response"]:::terminal
  DEAD --> REPORT

  ENGAGE["④ Run conversation sequence<br/>• Skill: conversation-planner<br/>• One five-step path per prospect<br/>• Each turn runs the four phases below"]:::step

  subgraph SEQ["Five-step message path (advance on positive reply)"]
    direction TB
    S1["Step 1 — Intro<br/>~300–500 chars"]:::step
    S2["Step 2 — Career deep dive<br/>≤ 500 chars"]:::step
    S3["Step 3 — Career plan<br/>≤ 500 chars"]:::step
    S4["Step 4 — The ask<br/>Resume / next step · ≤ 500 chars"]:::step
    S5["Step 5 — Close<br/>≤ 500 chars"]:::step
    S1 -->|Positive reply| S2
    S2 -->|Positive reply| S3
    S3 -->|Positive reply| S4
    S4 -->|Positive reply| S5
  end

  ENGAGE --> SEQ

  subgraph CYCLE["One planner cycle (four phases)"]
    direction TB
    CA["Phase A — Sync<br/>• fetch_chat_history<br/>• Merge new messages · dedupe thread"]:::phase
    CB["Phase B — Plan<br/>• Load state via MCP · run state machine<br/>• Draft next message · log PlannedMessage"]:::phase
    CC["Phase C — Deliver<br/>• send_message via MCP<br/>• Playwright sends · human-like pacing"]:::phase
    CD["Phase D — Persist<br/>• upsert_conversation · upsert_prospect<br/>• append_action_log"]:::phase
    CA --> CB --> CC --> CD
  end

  SEQ --> CYCLE

  subgraph EXITS["Exit reasons (any step / phase)"]
    direction TB
    E1["No reply ≥ 48h · ended_reason: no_response"]:::terminal
    E2["Prospect declines · ended_reason: not_interested"]:::terminal
    E3["Resume received · ended_reason: resume_received"]:::terminal
    E4["Call scheduled · ended_reason: call_scheduled"]:::terminal
    E5["Step 5 delivered · sequence complete"]:::terminal
  end

  CYCLE --> EXITS

  REPORT["⑤ End & report<br/>• Render Markdown summary · MCP: save_outreach_report<br/>• Final upsert_conversation · upsert_prospect · stage: ended<br/>• append_action_log · conversation_ended"]:::step

  EXITS --> REPORT
  REPORT --> DONE(["Outreach complete"]):::gate

  %% Optional batch entry — vertical hook into same cycle
  BATCH(["Batch mode"]):::batch
  BATCH --> BFLOW["Load connection list<br/>• Filter to actionable prospects<br/>• Run one full cycle per row<br/>• Write batch summary to log"]:::batch
  BFLOW --> CYCLE

```



