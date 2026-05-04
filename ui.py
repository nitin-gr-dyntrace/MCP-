from __future__ import annotations
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from dynatrace_mcp.app import (
    build_bug_escalation_text,
    build_customer_response_text,
    build_follow_up_text,
    build_investigation_plan_text,
    build_triage_text,
)
from dynatrace_mcp.feedback import get_feedback_store

HOST = "127.0.0.1"
PORT = 8765

OUTPUT_MODES = {
    "triage": ("Triage", build_triage_text),
    "investigation": ("Investigation Plan", build_investigation_plan_text),
    "customer_response": ("Customer Response", build_customer_response_text),
    "bug_escalation": ("Bug Escalation", build_bug_escalation_text),
}

ALL_MODES = list(OUTPUT_MODES.keys()) + ["follow_up"]


def _mode_pills(mode: str) -> str:
    pills = []
    for key, (label, _) in OUTPUT_MODES.items():
        checked = "checked" if key == mode else ""
        pills.append(
            f'<label class="pill">'
            f'<input type="radio" name="mode" value="{key}" {checked} onchange="toggleMode()">'
            f'{html.escape(label)}</label>'
        )
    follow_checked = "checked" if mode == "follow_up" else ""
    pills.append(
        f'<label class="pill pill-follow">'
        f'<input type="radio" name="mode" value="follow_up" {follow_checked} onchange="toggleMode()">'
        f'Follow Up</label>'
    )
    return "".join(pills)


def _feedback_panel(original_problem: str) -> str:
    if not original_problem:
        return ""
    esc = html.escape(original_problem)
    return f"""<div class="feedback-wrap">
  <p class="feedback-title">Was this answer helpful?</p>
  <div class="feedback-grid">
    <form method="post" action="/feedback" class="fb-form">
      <p class="fb-label">Something was wrong</p>
      <textarea name="fb_wrong" placeholder="What was incorrect..."></textarea>
      <textarea name="fb_correct" placeholder="The correct information..." style="margin-top:8px"></textarea>
      <input type="hidden" name="fb_type" value="correction">
      <input type="hidden" name="fb_problem" value="{esc}">
      <input type="text" name="fb_area" placeholder="Product area (optional)">
      <button type="submit" class="btn btn-danger">Submit Correction</button>
    </form>
    <form method="post" action="/feedback" class="fb-form">
      <p class="fb-label">This was correct</p>
      <textarea name="fb_confirm" placeholder="What guidance or fix worked..."></textarea>
      <input type="hidden" name="fb_type" value="confirmation">
      <input type="hidden" name="fb_problem" value="{esc}">
      <input type="text" name="fb_area" placeholder="Product area (optional)">
      <button type="submit" class="btn btn-confirm">Confirm Answer</button>
    </form>
  </div>
</div>"""


def _result_panel(output: str, error: str, original_problem: str = "") -> str:
    if output:
        return (
            f'<div class="card result-card">'
            f'<p class="card-label">Result</p>'
            f'<pre>{html.escape(output)}</pre>'
            f'</div>'
            + (_feedback_panel(original_problem))
        )
    if error:
        return (
            f'<div class="card result-card error-card">'
            f'<p class="card-label">Error</p>'
            f'<pre>{html.escape(error)}</pre>'
            f'</div>'
        )
    return (
        '<div class="card result-card empty-card">'
        '<p class="card-label">Result</p>'
        '<p class="empty-hint">Your result will appear here after you run the analysis.</p>'
        '</div>'
    )


CSS = """
:root {
  --bg:      #f5f0ea;
  --card:    #ffffff;
  --border:  #e2d9ce;
  --text:    #1c1712;
  --muted:   #70675e;
  --accent:  #0f766e;
  --accent2: #e6f7f5;
  --danger:  #be123c;
  --radius:  14px;
  --shadow:  0 4px 24px rgba(0,0,0,0.07);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 14px;
  line-height: 1.5;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
}
.page { max-width: 1280px; margin: 0 auto; padding: 24px 20px 48px; }

/* Header */
.header { margin-bottom: 24px; }
.header h1 { font-size: 26px; font-weight: 700; letter-spacing: -0.5px; color: var(--text); }
.header p  { margin-top: 4px; color: var(--muted); font-size: 13px; }

/* Layout */
.layout {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 20px;
  align-items: start;
}

/* Cards */
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.card-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  padding: 16px 18px 0;
}
.card-body { padding: 14px 18px 18px; }

/* Mode pills */
.pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 14px 18px 0;
}
.pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 1.5px solid var(--border);
  border-radius: 999px;
  background: #faf8f5;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  color: var(--muted);
  transition: border-color 0.15s, color 0.15s, background 0.15s;
  white-space: nowrap;
  user-select: none;
}
.pill input[type="radio"] { display: none; }
.pill:has(input:checked) {
  border-color: var(--accent);
  background: var(--accent2);
  color: var(--accent);
}
.pill-follow { border-color: #d1fae5; color: #065f46; }
.pill-follow:has(input:checked) { border-color: #059669; background: #d1fae5; color: #065f46; }

/* Form elements */
.field { margin-bottom: 14px; }
.field label { display: block; font-size: 12px; font-weight: 500; color: var(--muted); margin-bottom: 6px; }
textarea, input[type="text"], input[type="number"] {
  width: 100%;
  border: 1.5px solid var(--border);
  border-radius: 10px;
  padding: 10px 12px;
  font: inherit;
  font-size: 13px;
  background: #faf8f5;
  color: var(--text);
  outline: none;
  transition: border-color 0.15s;
}
textarea:focus, input:focus { border-color: var(--accent); }
textarea { resize: vertical; min-height: 160px; }

.row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 14px; }

.sources { display: flex; gap: 14px; margin-top: 6px; }
.sources label { display: flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; }
input[type="checkbox"] { accent-color: var(--accent); width: 15px; height: 15px; }

/* Buttons */
.btn {
  display: inline-block;
  border: none;
  border-radius: 999px;
  padding: 10px 22px;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.15s;
}
.btn:hover { opacity: 0.88; }
.btn-primary { background: var(--accent); color: #fff; }
.btn-danger  { background: var(--danger); color: #fff; width: 100%; margin-top: 10px; }
.btn-confirm { background: var(--accent); color: #fff; width: 100%; margin-top: 10px; }

/* Hidden input sections */
#case-input, #followup-input { margin-top: 14px; }

/* Result panel */
.result-card { min-height: 520px; }
.result-card pre {
  padding: 16px 18px 20px;
  font-family: "SF Mono", ui-monospace, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  background: #fafafa;
  color: var(--text);
}
.empty-card { display: flex; flex-direction: column; }
.empty-hint {
  padding: 40px 18px;
  color: var(--muted);
  font-size: 13px;
  text-align: center;
}
.error-card pre { color: var(--danger); }

/* Feedback */
.feedback-wrap {
  margin-top: 16px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 16px 18px 18px;
}
.feedback-title {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 14px;
}
.feedback-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.fb-form textarea { min-height: 72px; }
.fb-form input[type="text"] { margin-top: 8px; }
.fb-label { font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 8px; }

/* Session hint */
.session-hint { font-size: 12px; color: var(--muted); margin-top: 8px; }

@media (max-width: 860px) {
  .layout         { grid-template-columns: 1fr; }
  .feedback-grid  { grid-template-columns: 1fr; }
  .row            { grid-template-columns: 1fr; }
}
"""


def render_page(
    *,
    problem_statement: str = "",
    session_id: str = "",
    follow_up_message: str = "",
    sources: list[str] | None = None,
    mode: str = "triage",
    max_results: int = 6,
    output: str = "",
    error: str = "",
) -> str:
    sel = sources or ["docs", "community"]
    docs_chk      = "checked" if "docs"      in sel else ""
    community_chk = "checked" if "community" in sel else ""
    is_follow_up  = (mode == "follow_up")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>TraceSage 2.0</title>
  <style>{CSS}</style>
</head>
<body>
<div class="page">

  <div class="header">
    <h1>TraceSage 2.0</h1>
    <p>Paste a support case, pick a mode, and run. Copy the Session ID to continue the conversation with Follow Up.</p>
  </div>

  <div class="layout">

    <!-- Left: Input card -->
    <form class="card" method="post">

      <p class="card-label">Mode</p>
      <div class="pills">
        {_mode_pills(mode)}
      </div>

      <!-- Normal case input -->
      <div id="case-input" class="card-body" {'style="display:none"' if is_follow_up else ''}>
        <div class="field">
          <label for="problem_statement">Customer issue</label>
          <textarea id="problem_statement" name="problem_statement"
            placeholder="Paste a real support case here...">{html.escape(problem_statement)}</textarea>
        </div>

        <div class="row">
          <div class="field">
            <label>Sources</label>
            <div class="sources">
              <label><input type="checkbox" name="sources" value="docs" {docs_chk}> Docs</label>
              <label><input type="checkbox" name="sources" value="community" {community_chk}> Community</label>
            </div>
          </div>
          <div class="field">
            <label for="max_results">Max results</label>
            <input id="max_results" type="number" name="max_results" min="1" max="10" value="{max_results}">
          </div>
        </div>

        <button type="submit" class="btn btn-primary">Run Analysis</button>
      </div>

      <!-- Follow Up input -->
      <div id="followup-input" class="card-body" {'style="display:none"' if not is_follow_up else ''}>
        <div class="field">
          <label for="session_id">Session ID</label>
          <input type="text" id="session_id" name="session_id"
            placeholder="e.g. 5998bce0-ae8"
            value="{html.escape(session_id)}">
        </div>
        <div class="field">
          <label for="follow_up_message">Your message</label>
          <textarea id="follow_up_message" name="follow_up_message"
            placeholder="Add new info, ask a question, or share what the customer just said..."
            style="min-height:120px">{html.escape(follow_up_message)}</textarea>
        </div>

        <div class="row">
          <div class="field">
            <label>Sources</label>
            <div class="sources">
              <label><input type="checkbox" name="sources" value="docs" {docs_chk}> Docs</label>
              <label><input type="checkbox" name="sources" value="community" {community_chk}> Community</label>
            </div>
          </div>
          <div class="field">
            <label for="max_results2">Max results</label>
            <input id="max_results2" type="number" name="max_results" min="1" max="10" value="{max_results}">
          </div>
        </div>

        <p class="session-hint">The Session ID appears at the bottom of every result.</p>
        <button type="submit" class="btn btn-primary" style="margin-top:10px">Send Follow Up</button>
      </div>

    </form>

    <!-- Right: Result -->
    <div>
      {_result_panel(output, error, problem_statement)}
    </div>

  </div>
</div>

<script>
  function toggleMode() {{
    const mode = document.querySelector('input[name="mode"]:checked').value;
    const fu = mode === 'follow_up';
    document.getElementById('case-input').style.display    = fu ? 'none' : '';
    document.getElementById('followup-input').style.display = fu ? ''     : 'none';
  }}
</script>
</body>
</html>"""


class MCPUIHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send_html(render_page())

    def do_POST(self) -> None:
        length  = int(self.headers.get("Content-Length", "0"))
        payload = parse_qs(self.rfile.read(length).decode("utf-8"))

        # Feedback submission
        if self.path == "/feedback":
            fb_type = payload.get("fb_type", [""])[0]
            problem = payload.get("fb_problem", [""])[0].strip()
            area    = payload.get("fb_area",    [""])[0].strip()
            store   = get_feedback_store()
            if fb_type == "correction":
                wrong   = payload.get("fb_wrong",   [""])[0].strip()
                correct = payload.get("fb_correct", [""])[0].strip()
                if problem and correct:
                    store.add_correction(problem, wrong, correct, area)
                    msg = "Correction saved. It will surface on all future similar queries."
                else:
                    msg = "Please fill in both the problem and the correct information."
            elif fb_type == "confirmation":
                confirm = payload.get("fb_confirm", [""])[0].strip()
                if problem and confirm:
                    store.add_confirmation(problem, confirm, area)
                    msg = "Confirmation saved. This will reinforce the answer for similar queries."
                else:
                    msg = "Please fill in both the problem and what was confirmed correct."
            else:
                msg = "Unknown feedback type."
            self._send_html(render_page(output=msg))
            return

        # Main form
        mode    = payload.get("mode",    ["triage"])[0]
        sources = payload.get("sources", ["docs", "community"]) or ["docs", "community"]
        try:
            max_results = max(1, min(10, int(payload.get("max_results", ["6"])[0])))
        except ValueError:
            max_results = 6

        # Follow Up mode
        if mode == "follow_up":
            session_id = payload.get("session_id",        [""])[0].strip()
            message    = payload.get("follow_up_message", [""])[0].strip()
            if not session_id or not message:
                self._send_html(render_page(
                    mode=mode, sources=sources, max_results=max_results,
                    session_id=session_id, follow_up_message=message,
                    error="Please enter both a Session ID and a follow-up message.",
                ))
                return
            try:
                output = build_follow_up_text(session_id, message, sources, max_results)
            except Exception as exc:
                output = None
                err = str(exc)
            else:
                err = ""
            self._send_html(render_page(
                mode=mode, sources=sources, max_results=max_results,
                session_id=session_id, follow_up_message=message,
                output=output or "", error=err,
            ))
            return

        # Normal modes
        problem_statement = payload.get("problem_statement", [""])[0].strip()
        if mode not in OUTPUT_MODES:
            mode = "triage"
        if not problem_statement:
            self._send_html(render_page(
                problem_statement=problem_statement, sources=sources,
                mode=mode, max_results=max_results,
                error="Please enter a customer issue before running the analysis.",
            ))
            return

        try:
            _, builder = OUTPUT_MODES[mode]
            output = builder(problem_statement, sources, max_results)
            err    = ""
        except Exception as exc:
            output = ""
            err    = str(exc)

        self._send_html(render_page(
            problem_statement=problem_statement, sources=sources,
            mode=mode, max_results=max_results, output=output, error=err,
        ))

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_html(self, content: str) -> None:
        encoded = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), MCPUIHandler)
    print(json.dumps({"url": f"http://{HOST}:{PORT}", "host": HOST, "port": PORT}, indent=2))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
