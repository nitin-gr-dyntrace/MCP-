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


def _mode_cards(mode: str) -> str:
    cards = []
    for key, (label, _) in OUTPUT_MODES.items():
        checked = "checked" if key == mode else ""
        cards.append(
            f'<label class="mode-card">'
            f'<input type="radio" name="mode" value="{html.escape(key)}" {checked} onchange="toggleMode()">'
            f'<span>{html.escape(label)}</span></label>'
        )
    follow_checked = "checked" if mode == "follow_up" else ""
    cards.append(
        f'<label class="mode-card follow-card">'
        f'<input type="radio" name="mode" value="follow_up" {follow_checked} onchange="toggleMode()">'
        f'<span>Follow Up</span></label>'
    )
    return "\n".join(cards)


def _feedback_panel(original_problem: str) -> str:
    if not original_problem:
        return ""
    esc = html.escape(original_problem)
    return f"""
<section class="panel" style="margin-top:18px">
  <div class="panel-header"><h2>Was this answer helpful?</h2></div>
  <div class="panel-body">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
      <form method="post" action="/feedback">
        <input type="hidden" name="fb_type" value="correction">
        <input type="hidden" name="fb_problem" value="{esc}">
        <label class="block">What was wrong?</label>
        <textarea name="fb_wrong" style="min-height:70px" placeholder="Briefly describe the error..."></textarea>
        <label class="block" style="margin-top:10px">Correct information</label>
        <textarea name="fb_correct" style="min-height:70px" placeholder="Provide the right guidance..."></textarea>
        <input type="text" name="fb_area" placeholder="Product area (optional)" style="margin-top:10px">
        <button type="submit" style="margin-top:8px;background:#9f1239">Submit Correction</button>
      </form>
      <form method="post" action="/feedback">
        <input type="hidden" name="fb_type" value="confirmation">
        <input type="hidden" name="fb_problem" value="{esc}">
        <label class="block">What was correct?</label>
        <textarea name="fb_confirm" style="min-height:70px" placeholder="Describe what insight or fix worked..."></textarea>
        <input type="text" name="fb_area" placeholder="Product area (optional)" style="margin-top:10px">
        <button type="submit" style="margin-top:8px">Confirm Answer</button>
      </form>
    </div>
  </div>
</section>"""


def _output_panel(output: str, error: str, original_problem: str = "") -> str:
    if output:
        return (
            '<section class="panel result-panel">'
            '<div class="panel-header"><h2>Result</h2></div>'
            f'<pre>{html.escape(output)}</pre>'
            '</section>'
            + _feedback_panel(original_problem)
        )
    if error:
        return (
            '<section class="panel result-panel error-panel">'
            '<div class="panel-header"><h2>Error</h2></div>'
            f'<pre>{html.escape(error)}</pre>'
            '</section>'
        )
    return (
        '<section class="panel result-panel">'
        '<div class="panel-header"><h2>Result</h2></div>'
        '<pre>Your result will appear here after you run the analysis.</pre>'
        '</section>'
    )


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
    selected = sources or ["docs", "community"]
    source_docs = "checked" if "docs" in selected else ""
    source_community = "checked" if "community" in selected else ""
    is_follow_up = mode == "follow_up"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TraceSage 2.0</title>
  <style>
    :root {{
      --bg: #f4efe8; --surface: #fffaf4; --surface-strong: #fff;
      --text: #1f1a16; --muted: #6b6057; --border: #d8c9bb;
      --accent: #0f766e; --accent-soft: #d8f3ef; --danger: #9f1239;
      --shadow: 0 18px 40px rgba(74,58,44,0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: Georgia,"Times New Roman",serif;
      background: radial-gradient(circle at top left,rgba(15,118,110,0.12),transparent 32%),
                  linear-gradient(180deg,#f7f2ea 0%,#efe7dc 100%);
      color: var(--text);
    }}
    .shell {{ width: min(1180px,calc(100vw - 32px)); margin: 24px auto 40px; display: grid; gap: 18px; }}
    .hero {{ background: var(--surface); border: 1px solid var(--border); border-radius: 22px;
             padding: 28px; box-shadow: var(--shadow); }}
    .hero h1 {{ margin: 0 0 8px; font-size: clamp(2rem,4vw,3.2rem); line-height: 0.95; letter-spacing: -0.04em; }}
    .hero p {{ margin: 0; max-width: 780px; color: var(--muted); font-size: 1.02rem; }}
    .grid {{ display: grid; grid-template-columns: minmax(300px,420px) minmax(0,1fr); gap: 18px; align-items: start; }}
    .panel {{ background: var(--surface-strong); border: 1px solid var(--border); border-radius: 22px;
              box-shadow: var(--shadow); overflow: hidden; }}
    .panel-header {{ padding: 18px 20px 0; }}
    .panel-header h2 {{ margin: 0; font-size: 1rem; letter-spacing: 0.02em;
                        text-transform: uppercase; color: var(--muted); }}
    .panel-body {{ padding: 18px 20px 20px; }}
    label.block {{ display: block; margin-bottom: 10px; font-size: 0.92rem; color: var(--muted); }}
    textarea {{ width: 100%; min-height: 170px; border-radius: 16px; border: 1px solid var(--border);
               padding: 14px 16px; font: inherit; resize: vertical; background: #fffdf9; color: var(--text); }}
    input[type="text"] {{ width: 100%; border-radius: 12px; border: 1px solid var(--border);
                          padding: 10px 12px; font: inherit; background: #fffdf9; color: var(--text); margin-bottom: 12px; }}
    .modes {{ display: grid; grid-template-columns: repeat(5,minmax(0,1fr)); gap: 8px; margin-bottom: 16px; }}
    .mode-card {{ display: flex; align-items: center; justify-content: center; gap: 6px;
                  padding: 10px 8px; border: 1px solid var(--border); border-radius: 14px;
                  background: #fffcf7; cursor: pointer; font-size: 0.82rem; text-align: center; }}
    .mode-card input {{ accent-color: var(--accent); flex: 0 0 auto; }}
    .mode-card span {{ line-height: 1.15; overflow-wrap: anywhere; }}
    .follow-card {{ border-color: var(--accent); background: var(--accent-soft); }}
    .controls {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }}
    .control-box {{ padding: 12px 14px; border-radius: 16px; border: 1px solid var(--border); background: #fffcf7; }}
    .source-list {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; }}
    .source-list label {{ display: flex; align-items: center; gap: 8px; font-size: 0.95rem; }}
    input[type="number"] {{ width: 100%; border-radius: 12px; border: 1px solid var(--border);
                            padding: 10px 12px; font: inherit; background: #fffdf9; }}
    .actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 6px; }}
    button[type="submit"] {{ border: 0; border-radius: 999px; background: var(--accent);
                             color: white; padding: 12px 22px; font: inherit; cursor: pointer; font-size: 1rem; }}
    pre {{ margin: 0; padding: 18px 20px 22px; white-space: pre-wrap; word-break: break-word;
           font-family: ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;
           font-size: 0.9rem; line-height: 1.5; background: #fffdfa; }}
    .error-panel pre {{ color: var(--danger); }}
    .result-panel {{ min-height: 640px; }}
    .session-hint {{ font-size: 0.82rem; color: var(--muted); margin-top: 6px; }}
    @media (max-width: 920px) {{
      .grid,.modes,.controls {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <h1>TraceSage 2.0</h1>
      <p>Paste a real support case, pick a mode, run analysis — then use <strong>Follow Up</strong> to continue the conversation with the Session ID.</p>
    </section>
    <section class="grid">
      <form class="panel" method="post">
        <div class="panel-header"><h2>Case Input</h2></div>
        <div class="panel-body">

          <div class="modes">{_mode_cards(mode)}</div>

          <!-- Normal case input (hidden when Follow Up) -->
          <div id="case-input" {'style="display:none"' if is_follow_up else ''}>
            <label class="block" for="problem_statement">Customer issue</label>
            <textarea id="problem_statement" name="problem_statement"
              placeholder="Paste a real support case here...">{html.escape(problem_statement)}</textarea>
          </div>

          <!-- Follow Up input (hidden unless Follow Up mode) -->
          <div id="followup-input" {'style="display:none"' if not is_follow_up else ''}>
            <label class="block" for="session_id">Session ID</label>
            <input type="text" id="session_id" name="session_id"
              placeholder="e.g. 5998bce0-ae8"
              value="{html.escape(session_id)}">
            <label class="block" for="follow_up_message">Your follow-up message</label>
            <textarea id="follow_up_message" name="follow_up_message"
              placeholder="Add new info, ask a question, or say what changed..."
              style="min-height:120px">{html.escape(follow_up_message)}</textarea>
            <p class="session-hint">The Session ID is shown at the bottom of every result. Paste it here to continue the conversation.</p>
          </div>

          <div class="controls" style="margin-top:14px">
            <div class="control-box">
              <div>Sources</div>
              <div class="source-list">
                <label><input type="checkbox" name="sources" value="docs" {source_docs}> Docs</label>
                <label><input type="checkbox" name="sources" value="community" {source_community}> Community</label>
              </div>
            </div>
            <div class="control-box">
              <label class="block" for="max_results">Max results</label>
              <input id="max_results" type="number" min="1" max="10" name="max_results" value="{max_results}">
            </div>
          </div>

          <div class="actions">
            <button type="submit">Run MCP Analysis</button>
          </div>
        </div>
      </form>

      {_output_panel(output, error, problem_statement)}
    </section>
  </main>
  <script>
    function toggleMode() {{
      const mode = document.querySelector('input[name="mode"]:checked').value;
      const isFollowUp = mode === 'follow_up';
      document.getElementById('case-input').style.display = isFollowUp ? 'none' : '';
      document.getElementById('followup-input').style.display = isFollowUp ? '' : 'none';
    }}
  </script>
</body>
</html>"""


class MCPUIHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send_html(render_page())

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = parse_qs(self.rfile.read(length).decode("utf-8"))

        if self.path == "/feedback":
            fb_type = payload.get("fb_type", [""])[0]
            problem = payload.get("fb_problem", [""])[0].strip()
            area = payload.get("fb_area", [""])[0].strip()
            store = get_feedback_store()
            if fb_type == "correction":
                wrong = payload.get("fb_wrong", [""])[0].strip()
                correct = payload.get("fb_correct", [""])[0].strip()
                if problem and correct:
                    store.add_correction(problem, wrong, correct, area)
                    msg = "Correction saved. It will be applied to future similar queries."
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

        mode = payload.get("mode", ["triage"])[0]
        sources = payload.get("sources", ["docs", "community"]) or ["docs", "community"]
        try:
            max_results = max(1, min(10, int(payload.get("max_results", ["6"])[0])))
        except ValueError:
            max_results = 6

        if mode == "follow_up":
            session_id = payload.get("session_id", [""])[0].strip()
            message = payload.get("follow_up_message", [""])[0].strip()
            if not session_id or not message:
                self._send_html(render_page(
                    mode=mode, sources=sources, max_results=max_results,
                    session_id=session_id, follow_up_message=message,
                    error="Please enter both a Session ID and a follow-up message.",
                ))
                return
            try:
                output = build_follow_up_text(session_id, message, sources, max_results)
                self._send_html(render_page(
                    mode=mode, sources=sources, max_results=max_results,
                    session_id=session_id, follow_up_message=message, output=output,
                ))
            except Exception as exc:
                self._send_html(render_page(
                    mode=mode, sources=sources, max_results=max_results,
                    session_id=session_id, follow_up_message=message, error=str(exc),
                ))
            return

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
            self._send_html(render_page(
                problem_statement=problem_statement, sources=sources,
                mode=mode, max_results=max_results, output=output,
            ))
        except Exception as exc:
            self._send_html(render_page(
                problem_statement=problem_statement, sources=sources,
                mode=mode, max_results=max_results, error=str(exc),
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
