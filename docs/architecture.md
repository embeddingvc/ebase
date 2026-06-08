# Architecture & capabilities

This repo wires Claude (via the MCP protocol) to a real LinkedIn session and a small set of repo-local JSON/JSONL files that act as the pipeline state.

## Components

- A **LinkedIn MCP server** (`tools/server.py`) that exposes LinkedIn actions as tools. Playwright attaches to a real Chrome session via CDP.
- A **queue-draining worker** (`outreach/worker.py`) for "run jobs from JSON queue files" automation.
- A **message planner** (`outreach/planner.py`) that can generate copy in **API mode** (Anthropic) or **stub mode** (offline).
- Claude **skills** under `outreach/skills/` that orchestrate end-to-end outreach using MCP tools (including **`setup-outreach`** for first-run profile configuration).

## What you can do

- **First-run setup**
  - Skill: **`setup-outreach`** — interactive wizard: **`scrape_profile`** → present draft persona → refine with operator → **`merge_conversation_planner_identity`**

- **Profile data**
  - `scrape_profile`: quick structured scrape (includes `recent_posts` and also captures `raw_text`)
  - `parse_profile`: deeper multi-page crawl with a **structured** output (`linkedin.parse_profile/v2`) and activity metrics (no raw page dump)
- **Connection + messaging**
  - `send_connection_request` (optional ≤300 char note)
  - `is_first_degree_connection` (used to promote pending → connected)
  - `fetch_chat_history`
  - `send_message`
- **Content / engagement**
  - `create_new_post`
  - `reply_to_post`
  - `browse_forever` (background "human-like" feed browsing)
- **Outreach persistence (server-managed filesystem I/O)**
  - `get_*`, `upsert_*`, `append_*`, `save_connection`, `save_outreach_report`, `remove_pending_queue_entry`

## High-level architecture

```mermaid
flowchart TB
  subgraph ARCH ["System Architecture"]
    direction LR
    L1["Claude + Skills\n(outreach/skills/*/SKILL.md)"]
    L2["MCP Server\nFastMCP\n(tools/server.py)"]
    L3["Playwright\nAttach to Chrome via CDP\n(outreach/browser.py)"]
    L4["LinkedIn"]
    L1 -->|"tool calls"| L2
    L2 -->|"browser automation"| L3
    L3 -->|"UI interactions"| L4
  end

  subgraph WORKER ["Optional automation path"]
    direction LR
    W1["Queue files\n(outreach/queue/*.json)"]
    W2["Worker\n(outreach/worker.py)"]
    W3["Planner\n(outreach/planner.py)"]
    W1 --> W2 --> W3
  end

  subgraph DATA ["Data (repo-local)"]
    direction LR
    D1["outreach/prospects/*.json"]
    D2["outreach/conversations/*.json"]
    D3["outreach/connections.json"]
    D4["outreach/logs/*.jsonl\n(actions + planned messages)"]
    D5["outreach/storage/reports/*.md"]
  end
```

## Detailed workflow

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

  WAIT["③ Wait for acceptance<br/>• Dashboard sweep: web/connection_sync_sweep.py (no LLM)<br/>• MCP: is_first_degree_connection<br/>• Playwright verifies connection state / badge"]:::step

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
