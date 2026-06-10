#!/usr/bin/env python3
"""Web dashboard for answering ask_human questions (stdlib only).

Vendored from the standalone agent-chat project (~/git/claude/mcp/ask_human);
keep behavior-identical so the two stay easy to diff.

    fleet ask-human web                                  # via the operator console
    python -m fleet.ask_human.web                        # or run the module directly
    ASK_HUMAN_WEB_ADDR=0.0.0.0:9000 fleet ask-human web  # bind elsewhere

A two-pane operator console: a left sidebar lists every pending question with
its metadata (who is asking, age, type, priority); selecting one opens it in the
main pane to answer (radios / checkboxes / free text). Submitting writes to the
shared SQLite store — which unblocks the waiting agent — and auto-advances to the
next question. The page polls a small JSON API (``/api/questions``) so new
questions appear live without wiping a half-typed answer. No third-party deps.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .store import QuestionStore

store = QuestionStore()

# Fully static single-page app: all dynamic data arrives via /api/questions, so
# nothing here needs server-side interpolation (keep it a plain string).
_PAGE = """<!doctype html>
<html lang=en>
<head>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>ask_human</title>
<style>
:root{
  color-scheme:dark;
  --bg:#0d0f14;--surface:#15181f;--surface-2:#1b1f28;--border:#272c37;
  --text:#e7e9ee;--muted:#98a2b3;--accent:#818cf8;--accent-soft:#1e2233;
  --amber:#fbbf24;--amber-soft:#2a2310;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;display:flex;background:var(--bg);color:var(--text);
  font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}

.sidebar{width:340px;min-width:300px;height:100vh;background:var(--surface);
  border-right:1px solid var(--border);display:flex;flex-direction:column}
.sidebar .head{padding:16px 18px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between}
.brand{display:flex;align-items:center;gap:8px;font-weight:700;font-size:15px}
.dot{width:8px;height:8px;border-radius:50%;background:#22c55e;
  box-shadow:0 0 0 3px rgba(34,197,94,.18);transition:background-color .2s,box-shadow .2s}
.dot.off{background:#3f3f46;box-shadow:none}
.count{color:var(--muted);font-size:12.5px;font-weight:500;font-variant-numeric:tabular-nums}
.list{flex:1;overflow-y:auto;padding:8px}

.item{padding:11px 12px;margin-bottom:4px;border:1px solid transparent;
  border-radius:10px;cursor:pointer}
.item:hover{background:var(--surface-2)}
.item.sel{background:var(--accent-soft);border-color:var(--accent)}
.item-top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.agent{font-weight:600;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.age{color:var(--muted);font-size:11.5px;white-space:nowrap;font-variant-numeric:tabular-nums}
.preview{color:var(--muted);font-size:12.5px;margin-top:3px;overflow:hidden;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.tags{display:flex;gap:6px;align-items:center;margin-top:8px;flex-wrap:wrap}
.tag{font-size:10.5px;font-weight:600;letter-spacing:.4px;text-transform:uppercase;
  padding:1px 7px;border-radius:999px;background:var(--surface-2);color:var(--muted)}
.tag.prio{background:var(--amber-soft);color:var(--amber)}
.tags .id{margin-left:auto;color:var(--muted);font:11px ui-monospace,SFMono-Regular,Menlo,monospace}

.main{flex:1;min-height:0;overflow-y:auto;padding:40px 48px}
.detail-head{margin-bottom:6px}
.detail-agent{font-size:22px;font-weight:700}
.detail-meta{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:8px;
  color:var(--muted);font-size:12.5px}
.detail-meta .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.detail-meta .prio{color:var(--amber);font-weight:600}
.detail-prompt{font-size:18px;font-weight:500;line-height:1.5;
  margin:18px 0 26px;white-space:pre-wrap}

.answer-form{max-width:620px}
.options{display:flex;flex-direction:column;gap:8px}
.opt{display:flex;align-items:center;gap:11px;padding:13px 15px;cursor:pointer;
  border:1px solid var(--border);border-radius:11px;background:var(--surface);
  transition:border-color .12s,background .12s}
.opt:hover{border-color:var(--accent)}
.opt:has(input:checked){border-color:var(--accent);background:var(--accent-soft)}
.opt input{width:17px;height:17px;margin:0;accent-color:var(--accent)}
.opt-text{font-size:14.5px}
.note-label{margin:20px 0 8px;padding-top:16px;border-top:1px solid var(--border);
  color:var(--muted);font-size:12.5px;font-weight:600;letter-spacing:.3px}
textarea{width:100%;min-height:84px;padding:13px 15px;font:inherit;resize:vertical;
  color:var(--text);background:var(--surface);
  border:1px solid var(--border);border-radius:11px}
textarea:focus{outline:2px solid var(--accent);outline-offset:1px}
.actions{display:flex;align-items:center;gap:14px;margin-top:18px}
button{padding:11px 20px;border:0;border-radius:10px;background:var(--accent);
  color:#fff;font-size:14px;font-weight:600;cursor:pointer}
button:hover{filter:brightness(1.06)}
button:disabled{opacity:.6;cursor:default}
.hint{color:var(--muted);font-size:12.5px}

.empty{padding:40px 12px;text-align:center;color:var(--muted);font-size:13px}
.empty-main{height:100%;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:12px;color:var(--muted)}
.empty-icon{width:46px;height:46px;border-radius:50%;background:var(--surface-2);
  display:flex;align-items:center;justify-content:center;font-size:20px}

#toast{position:fixed;bottom:22px;left:50%;
  transform:translateX(-50%) translateY(20px);
  background:#2a2f3a;color:#fff;padding:10px 18px;border-radius:10px;font-size:13px;
  opacity:0;pointer-events:none;transition:.25s;box-shadow:0 8px 24px rgba(0,0,0,.2)}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
</style>
</head>
<body>
<aside class=sidebar>
  <div class=head>
    <div class=brand><span class=dot></span> ask_human</div>
    <div class=count id=count>…</div>
  </div>
  <div class=list id=list></div>
</aside>
<main class=main id=main></main>
<div id=toast></div>
<noscript><p style="padding:24px">This dashboard requires JavaScript.</p></noscript>
<script>
const $ = s => document.querySelector(s);
let questions = [];
let selectedId = null;
let renderedDetailId;        // undefined => force a (re)render of the detail pane
let serverOffset = 0;        // serverNow - clientNow, in seconds

function relTime(ts){
  let s = Math.max(0, Math.floor(Date.now()/1000 + serverOffset - ts));
  if(s < 60) return s + "s";
  if(s < 3600) return Math.floor(s/60) + "m";
  if(s < 86400) return Math.floor(s/3600) + "h";
  return Math.floor(s/86400) + "d";
}
function typeLabel(q){ return !q.options ? "text" : (q.multi_select ? "multi" : "choice"); }
function h(tag, cls, text){
  const e = document.createElement(tag);
  if(cls) e.className = cls;
  if(text != null) e.textContent = text;
  return e;
}
function toast(msg){
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), 2600);
}

function renderList(){
  const list = $("#list");
  $("#count").textContent = questions.length + " pending";
  // Indicator: green dot (+ count in the tab title) when questions are hanging,
  // dim gray when the queue is empty.
  $(".dot").classList.toggle("off", questions.length === 0);
  document.title = questions.length ? "(" + questions.length + ") ask_human" : "ask_human";
  list.innerHTML = "";
  if(!questions.length){
    list.appendChild(h("div", "empty", "No pending questions."));
    return;
  }
  for(const q of questions){
    const item = h("div", "item" + (q.id === selectedId ? " sel" : ""));
    item.onclick = () => select(q.id);

    const top = h("div", "item-top");
    top.appendChild(h("span", "agent", q.agent_id || "unknown"));
    const age = h("span", "age", relTime(q.created_at));
    age.dataset.ts = q.created_at;
    top.appendChild(age);
    item.appendChild(top);

    item.appendChild(h("div", "preview", q.prompt));

    const tags = h("div", "tags");
    tags.appendChild(h("span", "tag", typeLabel(q)));
    if(q.priority) tags.appendChild(h("span", "tag prio", "prio " + q.priority));
    tags.appendChild(h("span", "id", q.id.slice(0, 8)));
    item.appendChild(tags);

    list.appendChild(item);
  }
}

function renderDetail(){
  renderedDetailId = selectedId;
  const main = $("#main");
  main.innerHTML = "";
  const q = questions.find(x => x.id === selectedId);
  if(!q){
    const e = h("div", "empty-main");
    e.appendChild(h("div", "empty-icon", "✓"));
    e.appendChild(h("div", null, questions.length
      ? "Select a question from the left."
      : "All caught up — no pending questions."));
    main.appendChild(e);
    return;
  }

  const head = h("div", "detail-head");
  head.appendChild(h("div", "detail-agent", q.agent_id || "unknown"));
  const meta = h("div", "detail-meta");
  meta.appendChild(h("span", "mono", "#" + q.id.slice(0, 8)));
  if(q.session_id) meta.appendChild(h("span", null, "session " + q.session_id));
  const asked = h("span", null, "asked " + relTime(q.created_at) + " ago");
  asked.dataset.tsAsked = q.created_at;
  meta.appendChild(asked);
  if(q.timeout_s) meta.appendChild(h("span", null, "timeout " + Math.round(q.timeout_s) + "s"));
  if(q.priority) meta.appendChild(h("span", "prio", "priority " + q.priority));
  head.appendChild(meta);
  main.appendChild(head);

  main.appendChild(h("div", "detail-prompt", q.prompt));

  const form = h("form", "answer-form");
  form.onsubmit = submit;
  if(q.options){
    const group = h("div", "options");
    for(const o of q.options){
      const lab = h("label", "opt");
      const inp = document.createElement("input");
      inp.type = q.multi_select ? "checkbox" : "radio";
      inp.name = "answer";
      inp.value = o;
      lab.appendChild(inp);
      lab.appendChild(h("span", "opt-text", o));
      group.appendChild(lab);
    }
    form.appendChild(group);

    // Always offer a free-text escape hatch beside the options: the operator can
    // pick an option AND add context, or skip the options entirely to answer in
    // prose / correct a wrong premise. This text is sent as `note` to the agent.
    form.appendChild(h("div", "note-label", "Add a note or correction (optional)"));
    const note = document.createElement("textarea");
    note.name = "note";
    note.placeholder = "None of these fit, or want to add context? Type it here — it's sent to the agent as a correction.";
    note.onkeydown = e => { if((e.metaKey || e.ctrlKey) && e.key === "Enter") form.requestSubmit(); };
    form.appendChild(note);
  } else {
    const ta = document.createElement("textarea");
    ta.name = "answer";
    ta.placeholder = "Type your answer…";
    ta.onkeydown = e => { if((e.metaKey || e.ctrlKey) && e.key === "Enter") form.requestSubmit(); };
    form.appendChild(ta);
  }

  const actions = h("div", "actions");
  const btn = h("button", null, q.options ? "Submit answer" : "Send");
  btn.type = "submit";
  actions.appendChild(btn);
  actions.appendChild(h("span", "hint", "⌘/Ctrl + Enter"));
  if(q.default_answer != null){
    const d = Array.isArray(q.default_answer) ? q.default_answer.join(", ") : q.default_answer;
    actions.appendChild(h("span", "hint", "default on timeout: " + d));
  }
  form.appendChild(actions);
  main.appendChild(form);

  const first = form.querySelector("textarea, input");
  if(first) first.focus();
}

function select(id){
  if(id === selectedId) return;
  selectedId = id;
  renderList();
  renderDetail();
}

async function submit(ev){
  ev.preventDefault();
  const q = questions.find(x => x.id === selectedId);
  if(!q) return;
  const form = ev.target;
  const body = new URLSearchParams();
  body.append("id", q.id);
  if(q.options){
    const checked = [...form.querySelectorAll("input[name=answer]:checked")];
    const note = (form.querySelector("textarea[name=note]")?.value || "").trim();
    if(!checked.length && !note){ toast("Pick an option or type a note."); return; }
    checked.forEach(c => body.append("answer", c.value));
    if(note) body.append("note", note);
  } else {
    const v = form.querySelector("textarea").value.trim();
    if(!v){ toast("Type an answer first."); return; }
    body.append("answer", v);
  }
  const btn = form.querySelector("button");
  btn.disabled = true;
  btn.textContent = "Sending…";
  let res;
  try{
    res = await (await fetch("/answer", {
      method: "POST",
      headers: {"Content-Type": "application/x-www-form-urlencoded"},
      body,
    })).json();
  }catch(e){
    btn.disabled = false;
    toast("Network error — try again.");
    return;
  }
  toast(res.ok ? "Answer sent" : "Already " + res.status + " — refreshing");
  selectedId = null;            // advance to the next pending question on reload
  renderedDetailId = undefined;
  await load();
}

async function load(){
  let data;
  try{ data = await (await fetch("/api/questions")).json(); }
  catch(e){ return; }
  serverOffset = data.now - Date.now()/1000;
  questions = data.pending;
  if(selectedId && !questions.find(q => q.id === selectedId)) selectedId = null;
  if(!selectedId && questions.length) selectedId = questions[0].id;
  renderList();
  if(selectedId !== renderedDetailId) renderDetail();   // never clobbers a half-typed answer
}

// Keep relative times ticking between 3s polls.
setInterval(() => {
  document.querySelectorAll("[data-ts]").forEach(el => { el.textContent = relTime(+el.dataset.ts); });
  document.querySelectorAll("[data-ts-asked]").forEach(el => {
    el.textContent = "asked " + relTime(+el.dataset.tsAsked) + " ago";
  });
}, 1000);

load();
setInterval(load, 3000);
</script>
</body>
</html>
"""


def _questions_payload() -> dict:
    """Everything the dashboard needs to render the list + detail panes."""
    return {
        "now": time.time(),
        "pending": [
            {
                "id": q["id"],
                "agent_id": q["agent_id"],
                "session_id": q["session_id"],
                "prompt": q["prompt"],
                "options": q["options"],
                "multi_select": q["multi_select"],
                "priority": q["priority"],
                "created_at": q["created_at"],
                "timeout_s": q["timeout_s"],
                "default_answer": q["default_answer"],
            }
            for q in store.list_pending()
        ],
    }


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: str = "", ctype: str = "text/html; charset=utf-8",
              headers: dict | None = None) -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, code: int, obj: object) -> None:
        self._send(code, json.dumps(obj), ctype="application/json")

    def do_GET(self):  # noqa: N802 (http.server API)
        if self.path.startswith("/favicon"):
            self._send(204)
        elif self.path.startswith("/api/questions"):
            self._send_json(200, _questions_payload())
        else:
            self._send(200, _PAGE)

    def do_POST(self):  # noqa: N802
        if not self.path.startswith("/answer"):
            self._send(404, "not found")
            return
        length = int(self.headers.get("Content-Length", 0))
        form = urllib.parse.parse_qs(self.rfile.read(length).decode())
        qid = (form.get("id") or [""])[0]
        answers = form.get("answer", [])
        note = (form.get("note") or [""])[0].strip() or None
        question = store.get(qid)
        ok, status = False, (question["status"] if question else "missing")
        if question and question["status"] == "pending":
            # No selection but a note → the note IS the answer (`answer` stays
            # null/empty so the agent knows to read `note` as the real reply).
            answer = answers if question["multi_select"] else (answers[0] if answers else None)
            ok = store.answer(qid, answer, note=note, answered_by="web")
            status = "answered" if ok else (store.get(qid) or {}).get("status", "missing")
        self._send_json(200, {"ok": ok, "status": status})

    def log_message(self, *args):  # keep the console quiet
        pass


def serve(addr: str | None = None) -> None:
    addr = addr or os.environ.get("ASK_HUMAN_WEB_ADDR", "127.0.0.1:8765")
    host, _, port = addr.partition(":")
    httpd = ThreadingHTTPServer((host, int(port or 8765)), _Handler)
    print(f"ask_human web dashboard on http://{host}:{port or 8765}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    serve()
