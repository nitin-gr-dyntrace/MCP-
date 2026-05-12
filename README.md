# TraceSage 2.0 — Dynatrace Support MCP Server

A Model Context Protocol (MCP) server that gives Claude and GitHub Copilot structured Dynatrace domain intelligence — live docs, playbooks, failure mode libraries, engineer-verified corrections, and session memory — so every support case gets a specific, actionable response instead of a generic one.

---

## What it does

| Mode | Output |
|---|---|
| **Triage** | Product area classification, matched playbooks, failure modes, questions, evidence checklist, customer draft |
| **Investigation Plan** | Ordered investigation steps, hypotheses, reference pack |
| **Customer Response** | Ready-to-send customer-facing reply |
| **Bug Escalation** | DE-ready escalation with component, expected vs actual, evidence |
| **Follow Up** | Continues a prior session with full context from previous turns |

**Self-learning** — when an engineer submits a correction, it is stored and automatically surfaced the next time a similar case comes in.

**Slack** — results can be posted directly to a Slack channel with one click.

---

## Requirements

- Python 3.11+
- No external pip packages — uses stdlib only

---

## Installation

```bash
git clone https://github.com/nitin-gr-dyntrace/MCP-.git
cd MCP-
```

No `pip install` needed.

---

## Running the Web UI

```bash
python ui.py
```

Open `http://127.0.0.1:8765` in your browser.

**Optional — enable Slack notifications:**

```bash
# Windows
set SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
python ui.py

# Mac / Linux
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL python ui.py
```

When `SLACK_WEBHOOK_URL` is set, a **Send to Slack** button appears on every result. It posts severity, product area, matched playbook, top questions, and session ID to your channel.

---

## Connect to GitHub Copilot in VS Code

**Requirements:** VS Code 1.99+ with the GitHub Copilot extension.

**Step 1 — The config file is already included.**
`.vscode/mcp.json` is in the repo. Open this project folder in VS Code and it is picked up automatically — no manual config needed.

**Step 2 — Enable MCP in VS Code.**
Open your user `settings.json` (`Ctrl+Shift+P` → *Open User Settings (JSON)*) and add:

```json
"chat.mcp.enabled": true
```

**Step 3 — Activate the server in Copilot Chat.**
- Open Copilot Chat (`Ctrl+Alt+I`)
- Click the **Tools** icon (plug icon) at the bottom of the chat panel
- Enable **dynatrace-support**

**Step 4 — Use it.**

```
Use dynatrace-support to triage this case: <paste case text>
```

```
Use dynatrace-support to build a bug escalation for: <paste case text>
```

```
Use dynatrace-support follow_up with session abc-123: the customer says the issue started after upgrading the operator to 0.13
```

Copilot calls the MCP tools, gets structured diagnosis + live Dynatrace doc references, and writes a specific response for the exact problem described.

---

## Connect to Claude Desktop

**Step 1 — Find your Claude Desktop config file.**

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Mac | `~/Library/Application Support/Claude/claude_desktop_config.json` |

**Step 2 — Add this block to the config file.**

```json
{
  "mcpServers": {
    "dynatrace-support": {
      "command": "python",
      "args": ["C:\\Users\\yourname\\MCP\\MCP-\\server.py"]
    }
  }
}
```

> Mac/Linux: use forward slashes — `"/Users/yourname/MCP/MCP-/server.py"`

**Step 3 — Restart Claude Desktop.**

The tools `triage_case`, `build_investigation_plan`, `build_customer_response`, `build_bug_escalation`, `follow_up`, `submit_correction`, `confirm_answer`, `list_feedback_stats` will appear in Claude's tool panel.

---

## Slack Webhook Setup

1. In your Slack workspace go to **Apps** → search **Incoming Webhooks** → **Add to Slack**
2. Choose your support channel → **Add Incoming Webhooks Integration**
3. Copy the Webhook URL (`https://hooks.slack.com/services/...`)
4. Set `SLACK_WEBHOOK_URL` before starting the UI

Each Slack post includes severity emoji, product area, playbook matched, top 3 questions to ask, and the session ID for follow-up.

---

## Self-Learning (Feedback Loop)

After every result the **"Was this answer helpful?"** panel appears.

- **Submit Correction** — enter what was wrong and what the correct information is. Saved to `.cache/learned_facts.json`.
- **Confirm Answer** — confirm what worked. Saved as a positive signal.

The next time a similar case runs, the correction surfaces at the top:

```
=== LEARNED FROM PAST CASES ===
[!] Verified Correction  (match 72% | area: Extensions)
   What was wrong : suggested restarting ActiveGate
   Correct info   : issue was IAM policy drift on the AWS integration role
================================
```

---

## Session Continuity (Follow Up)

Every result ends with a Session ID. To continue an investigation:

1. Copy the Session ID from the result footer (e.g. `5998bce0-ae8`)
2. Switch to **Follow Up** mode in the UI (or use the `follow_up` MCP tool)
3. Paste the Session ID and type your next message

The system keeps the last 4 turns of context — product area, severity, what was found — and re-diagnoses with the new information merged in.

---

## Adding Custom Playbooks

Edit `playbooks.json` in the project root:

```json
{
  "id": "unique_id",
  "product_area": "Extensions",
  "title": "Short descriptive title",
  "triggers": ["exact phrase that must appear in the case text"],
  "keywords": ["supporting keyword"],
  "failure_domains": ["What breaks in this scenario"],
  "questions": ["What to ask the customer"],
  "evidence": ["What logs or data to collect"],
  "mitigations": ["Steps to try first"],
  "escalate_when": ["Condition that warrants DE escalation"]
}
```

**Available product areas:** `OneAgent`, `ActiveGate`, `Log Monitoring`, `Extensions`, `DEM`, `Kubernetes Monitoring`, `API / Authentication`, `Metrics Ingestion`, `Davis / Alerting`, `Grail / DQL`, `Cloud Integration`

---

## Project Structure

```
├── server.py              # MCP stdio server entry point
├── ui.py                  # Web UI  →  http://127.0.0.1:8765
├── playbooks.json         # Triage playbooks — add your own here
├── .vscode/
│   └── mcp.json           # VS Code / Copilot MCP config (ready to use)
└── dynatrace_mcp/
    ├── app.py             # Output builders, search, session logic
    ├── config.py          # Product area profiles, keywords, synonyms
    ├── diagnosis.py       # Classification, concern types, severity
    ├── failure_modes.py   # Failure mode library and inference weights
    ├── feedback.py        # Self-learning correction and confirmation store
    ├── session.py         # Session persistence and follow-up context
    ├── models.py          # Shared data classes
    └── playbooks.py       # Playbook loader with in-memory cache
```
