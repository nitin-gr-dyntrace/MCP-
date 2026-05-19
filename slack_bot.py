"""
Tracesage — Slack bot for Dynatrace Support MCP.

Usage:
    set SLACK_BOT_TOKEN=xoxb-...
    set SLACK_APP_TOKEN=xapp-...
    python slack_bot.py

Then in any Slack channel where Tracesage is invited:
    @Tracesage triage: OneAgent stopped sending data after upgrade on 50 Linux hosts
    @Tracesage investigate: ActiveGate hitting soft limits on PostgreSQL Extension
    @Tracesage escalate: DEM synthetic monitors failing after frontend rollout
    @Tracesage respond: Customer asks why metrics are missing after host restart
"""
from __future__ import annotations

import os
import sys
import re

# ---------------------------------------------------------------------------
# Ensure the MCP project root is on the path
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from dynatrace_mcp.app import (
    build_triage_text,
    build_investigation_plan_text,
    build_bug_escalation_text,
    build_customer_response_text,
)

# ---------------------------------------------------------------------------
# Config — set via environment variables
# ---------------------------------------------------------------------------
# Auto-load .env file — no need to set env vars manually ever again
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN", "")  # xapp-...

if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
    print(
        "ERROR: .env file missing tokens.\n"
        "Add these to C:\\Users\\nitin.gr\\MCP\\Dynatrace-MCP\\.env:\n"
        "  SLACK_BOT_TOKEN=xoxb-...\n"
        "  SLACK_APP_TOKEN=xapp-..."
    )
    sys.exit(1)

print(f"[INFO] Tokens loaded ✅ BOT=...{SLACK_BOT_TOKEN[-6:]} APP=...{SLACK_APP_TOKEN[-6:]}")

DEFAULT_SOURCES = ["docs", "community"]
DEFAULT_MAX_RESULTS = 4

# ---------------------------------------------------------------------------
# Slack app
# ---------------------------------------------------------------------------
app = App(token=SLACK_BOT_TOKEN)


# ---------------------------------------------------------------------------
# Command parser
# ---------------------------------------------------------------------------
_COMMAND_RE = re.compile(
    r"(?:triage|investigate|escalate|respond|analyze|search)[:\s]",
    re.IGNORECASE,
)

def _detect_command(text: str) -> tuple[str, str]:
    """
    Returns (command, problem_text).
    command is one of: triage | investigate | escalate | respond | analyze | unknown
    """
    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    lower = clean.lower()

    if lower.startswith(("triage", "triage:")):
        return "triage", re.sub(r"^triage:?\s*", "", clean, flags=re.IGNORECASE).strip()
    if lower.startswith(("investigate", "investigate:")):
        return "investigate", re.sub(r"^investigate:?\s*", "", clean, flags=re.IGNORECASE).strip()
    if lower.startswith(("escalate", "escalate:")):
        return "escalate", re.sub(r"^escalate:?\s*", "", clean, flags=re.IGNORECASE).strip()
    if lower.startswith(("respond", "respond:", "response", "response:")):
        return "respond", re.sub(r"^respon[ds]e?:?\s*", "", clean, flags=re.IGNORECASE).strip()
    if lower.startswith(("analyze", "analyze:", "analyse", "analyse:")):
        return "analyze", re.sub(r"^analys[ez]e?:?\s*", "", clean, flags=re.IGNORECASE).strip()

    # No prefix — default to triage
    return "triage", clean


def _run_mcp_tool(command: str, problem: str) -> str:
    """Call the right MCP tool and return the text result."""
    if not problem:
        return (
            "👋 *Tracesage here!* Tell me the case and I'll get to work.\n\n"
            "*Commands:*\n"
            "• `@Tracesage triage: <case>`\n"
            "• `@Tracesage investigate: <case>`\n"
            "• `@Tracesage escalate: <case>`\n"
            "• `@Tracesage respond: <case>`\n"
            "• `@Tracesage analyze: <case>`"
        )

    try:
        if command == "triage":
            return build_triage_text(problem, DEFAULT_SOURCES, DEFAULT_MAX_RESULTS)
        elif command == "investigate":
            return build_investigation_plan_text(problem, DEFAULT_SOURCES, DEFAULT_MAX_RESULTS)
        elif command == "escalate":
            return build_bug_escalation_text(problem, DEFAULT_SOURCES, DEFAULT_MAX_RESULTS)
        elif command == "respond":
            return build_customer_response_text(problem, DEFAULT_SOURCES, DEFAULT_MAX_RESULTS)
        elif command == "analyze":
            return build_triage_text(problem, DEFAULT_SOURCES, DEFAULT_MAX_RESULTS)
        else:
            return build_triage_text(problem, DEFAULT_SOURCES, DEFAULT_MAX_RESULTS)
    except Exception as exc:
        return f"❌ MCP error: {exc}"


def _format_for_slack(text: str) -> str:
    """Trim to Slack's 3000-char block limit and wrap in a code block."""
    max_len = 2800
    if len(text) > max_len:
        text = text[:max_len] + "\n\n... _(truncated — run full triage in Claude Desktop for complete output)_"
    return f"```\n{text}\n```"


# ---------------------------------------------------------------------------
# Event handler — @mention (runs MCP in background thread to avoid Slack timeout)
# ---------------------------------------------------------------------------
import threading

@app.event("app_mention")
def handle_mention(ack, event, say, client):
    ack()  # Acknowledge within 3 seconds — required
    user    = event.get("user", "there")
    channel = event.get("channel")
    text    = event.get("text", "")
    print(f"[EVENT] app_mention received from {user} in {channel}: {text[:80]}")

    def process():
        try:
            # Post ack message
            ack_msg = client.chat_postMessage(
                channel=channel,
                text=f"🔍 *Tracesage* is on it <@{user}>... running triage now!",
            )
            thread_ts = ack_msg.get("ts")
            command, problem = _detect_command(text)
            print(f"[INFO] Command={command} | Problem={problem[:80]}")
            result   = _run_mcp_tool(command, problem)
            formatted = _format_for_slack(result)
            client.chat_postMessage(
                channel=channel,
                text=formatted,
                thread_ts=thread_ts,
            )
            print(f"[INFO] ✅ Response posted to {channel}")
        except Exception as e:
            print(f"[ERROR] {e}")
            try:
                say(f"❌ Error: `{e}`")
            except Exception:
                pass

    threading.Thread(target=process, daemon=True).start()


# Catch-all to debug any unhandled events
@app.event("message")
def handle_message_events(body):
    print(f"[DEBUG] message event: {str(body)[:120]}")


# ---------------------------------------------------------------------------
# Also handle direct messages
# ---------------------------------------------------------------------------
@app.message(re.compile(r"(triage|investigate|escalate|respond|analyze)", re.IGNORECASE))
def handle_dm(message, say):
    text = message.get("text", "")
    command, problem = _detect_command(text)
    result = _run_mcp_tool(command, problem)
    say(_format_for_slack(result))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("🚀 Tracesage bot starting in Socket Mode...")
    print(f"   MCP tools: triage | investigate | escalate | respond | analyze")
    print(f"   Sources  : {DEFAULT_SOURCES}")
    print()
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
