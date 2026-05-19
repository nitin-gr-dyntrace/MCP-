# TraceSage — Dynatrace Support MCP Server

A Model Context Protocol (MCP) server that gives Claude and GitHub Copilot structured Dynatrace domain intelligence — live docs, semantic search, playbooks, failure mode libraries, contradiction detection, engineer-verified corrections, and session memory — so every support case gets a specific, actionable response instead of a generic one.

---

## What it does

| Mode | Output |
|---|---|
| **Triage** | Product area classification, matched playbooks, failure modes, questions, evidence checklist, customer draft |
| **Investigation Plan** | Ordered investigation steps, hypotheses, reference pack |
| **Customer Response** | Ready-to-send customer-facing reply |
| **Bug Escalation** | Engineering-ready escalation with component, expected vs actual, evidence |
| **Follow Up** | Continues a prior session with full context from previous turns |
| **Contradiction Detection** | Flags when a new case conflicts with a prior resolution |

**Self-learning** — when an engineer submits a correction, it is stored and automatically surfaced the next time a similar case comes in.

**Semantic Search** — uses `sentence-transformers` (`all-MiniLM-L6-v2`) for embedding-based reranking on top of TF-IDF, so intent-based queries match correctly even without exact keyword overlap.

**Slack Bot** — `@tracesage` in any channel triggers full triage, investigation, escalation, or customer response — all powered by the MCP server.

---

## Requirements

- Python 3.11+
- Dependencies: `mcp[cli]`, `sentence-transformers`, `numpy`, `slack-bolt`, `python-dotenv`

---

## Installation

```bash
git clone https://github.com/nitin-gr-dyntrace/MCP-.git
cd MCP-
pip install "mcp[cli]" sentence-transformers numpy slack-bolt python-dotenv
```

---

## Running the MCP Server

```bash
python server_sdk.py
```

This starts the MCP server over `stdio` using the official MCP Python SDK — fully compatible with Claude Desktop and VS Code Copilot.

---

## Running the Web UI

```bash
python ui.py
```

Open `http://127.0.0.1:8765` in your browser.

---

## Connect to Claude Desktop

**Step 1 — Find your Claude Desktop config file.**

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Mac | `~/Library/Application Support/Claude/claude_desktop_config.json` |

**Step 2 — Add this block.**

```json
{
  "mcpServers": {
    "dynatrace-support": {
      "command": "python",
      "args": ["C:\\Users\\yourname\\MCP\\MCP-\\server_sdk.py"],
      "cwd": "C:\\Users\\yourname\\MCP\\MCP-"
    }
  }
}
```

> Mac/Linux: use forward slashes — `"/Users/yourname/MCP/MCP-/server_sdk.py"`

**Step 3 — Restart Claude Desktop.**

Click `+` → **Connectors** → toggle `dynatrace-support` ON.

---

## Connect to GitHub Copilot in VS Code

**Step 1** — `.vscode/mcp.json` is already in the repo. Open the project in VS Code — it is picked up automatically.

**Step 2** — Open User Settings (`Ctrl+Shift+P` → *Open User Settings JSON*) and add:

```json
"chat.mcp.enabled": true
```

**Step 3** — Open Copilot Chat → click the **Tools** icon → enable **dynatrace-support**.

---

## All 15 MCP Tools

### 🔍 Search & Read
| Tool | What it does |
|---|---|
| `search_dynatrace_knowledge` | Semantic search across DT docs + community |
| `search_support_sources` | Search across all configured connectors |
| `read_dynatrace_page` | Fetch and extract a specific DT URL |
| `check_url_access` | Validate if a URL is reachable from this machine |

### 🏥 Triage & Analysis
| Tool | What it does |
|---|---|
| `triage_case` | Full structured support triage with contradiction detection |
| `analyze_customer_concern` | Classify issue + suggest support path |
| `build_investigation_plan` | Ordered investigation steps with hypotheses |

### ✍️ Drafting
| Tool | What it does |
|---|---|
| `build_bug_escalation` | Engineering-ready escalation draft |
| `build_customer_response` | Polished customer-facing reply |

### 🧠 Memory & Sessions
| Tool | What it does |
|---|---|
| `follow_up` | Continue a prior case by session ID |
| `prime_topic_cache` | Pre-load docs for a topic into local cache |

### 📊 Connectors & Feedback
| Tool | What it does |
|---|---|
| `list_connectors` | Show live vs scaffolded connectors |
| `submit_correction` | Tell the MCP an answer was wrong |
| `confirm_answer` | Tell the MCP an answer was correct |
| `list_feedback_stats` | Show correction/confirmation stats |

---

## Slack Bot (Tracesage)

**Setup:**

1. Create a Slack app at `api.slack.com/apps`
2. Enable **Socket Mode** — generate an `xapp-` token
3. Subscribe to `app_mention` + `message.channels` events
4. Install to workspace — copy the `xoxb-` bot token
5. Create a `.env` file in the project root:

```env
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
```

**Run:**

```bash
python slack_bot.py
```

**Commands in Slack:**

| Command | Example |
|---|---|
| `triage` | `@tracesage triage: OneAgent stopped sending data after upgrade on 50 Linux hosts` |
| `investigate` | `@tracesage investigate: ActiveGate hitting soft limits on PostgreSQL Extension` |
| `escalate` | `@tracesage escalate: DEM synthetic monitors failing after frontend rollout` |
| `respond` | `@tracesage respond: Customer asks why metrics are missing after host restart` |
| `analyze` | `@tracesage analyze: Kubernetes monitoring showing intermittent gaps in pod visibility` |

---

## Semantic Search

Uses `sentence-transformers` with `all-MiniLM-L6-v2` for hybrid reranking:

```
score = 0.60 × embedding_cosine_similarity + 0.40 × TF-IDF_score
```

Embeddings are cached to `.cache/embeddings_cache.json` — first run is slower, subsequent runs are instant.

Falls back to pure TF-IDF if `sentence-transformers` is not installed.

---

## Contradiction Detection

Every `triage_case` call scans prior sessions for conflicts:

- **Version conflict** — same version was previously marked as resolved
- **Action conflict** — prior session recommended rollback, current suggests upgrade
- **Config conflict** — prior session said disable X, current says enable X

Conflicts appear as a `⚠️ CONTRADICTION WARNINGS` block in the triage output.

---

## Self-Learning (Feedback Loop)

After every result:

- **Submit Correction** — enter what was wrong and the correct info. Saved to `.cache/learned_facts.json`.
- **Confirm Answer** — confirm what worked. Saved as a positive signal.

Next time a similar case runs, the correction surfaces at the top:

```
=== LEARNED FROM PAST CASES ===
[!] Verified Correction  (match 72% | area: Extensions)
   What was wrong : suggested restarting ActiveGate
   Correct info   : issue was IAM policy drift on the AWS integration role
================================
```

---

## Session Continuity

Every result ends with a Session ID. To continue:

1. Copy the Session ID (e.g. `5998bce0-ae8`)
2. Use **Follow Up** mode in the UI or `follow_up` MCP tool
3. Paste the Session ID and type your next message

The system keeps the last 4 turns of context and re-diagnoses with new information merged in.

---

## Project Structure

```
├── server.py                      # Legacy MCP stdio entry point
├── server_sdk.py                  # MCP server using official SDK (use this)
├── slack_bot.py                   # Tracesage Slack bot
├── ui.py                          # Web UI → http://127.0.0.1:8765
├── playbooks.json                 # Triage playbooks — add your own here
├── eval.py                        # Evaluation harness
├── eval_cases.json                # Evaluation test cases
├── .env                           # Slack tokens (not committed)
├── .vscode/mcp.json               # VS Code / Copilot MCP config
└── dynatrace_mcp/
    ├── app.py                     # Output builders, search, session logic
    ├── config.py                  # Product area profiles, keywords, synonyms
    ├── diagnosis.py               # Classification, concern types, severity
    ├── embeddings.py              # Semantic search with sentence-transformers
    ├── contradiction.py           # Contradiction detection across sessions
    ├── failure_modes.py           # Failure mode library and inference weights
    ├── feedback.py                # Self-learning correction and confirmation store
    ├── session.py                 # Session persistence and follow-up context
    ├── models.py                  # Shared data classes
    └── playbooks.py               # Playbook loader with in-memory cache
```

---

## Connector Roadmap

Live now:
- `docs` — `docs.dynatrace.com`
- `community` — `community.dynatrace.com`
- `slack` — Tracesage bot via Socket Mode (`SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` in `.env`)

Scaffolded (ready to wire):
- `jira` — needs `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`
- `stackoverflow` — needs `STACKEXCHANGE_API_KEY`
