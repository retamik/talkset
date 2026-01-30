from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from typing import Optional
import html

from backend.db import init_db
from backend.crud_sqlite import (
    insert_message,
    list_kus,
    get_ku,
    get_or_create_default_project,
    finalize_due_batches,
)
from backend.scheduler import BatchScheduler
from config import settings

app = FastAPI()

# для тестов 5 секунд, прод-режима можно 60
scheduler = BatchScheduler(tick_seconds=5)


class TelegramMessageIn(BaseModel):
    chat_id: str
    text: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    message_id: Optional[str] = None
    sent_at: Optional[int] = None


@app.on_event("startup")
async def on_startup():
    init_db()
    get_or_create_default_project()
    await scheduler.start()
    print("✅ DB initialized, scheduler started")


@app.on_event("shutdown")
async def on_shutdown():
    await scheduler.stop()
    print(" Scheduler stopped")


@app.get("/health")
def health():
    return {
        "ok": True,
        "db_path": settings.db_path,
        "batch_window_seconds": settings.batch_window_seconds,
        "tick_seconds": 5,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
    }


@app.post("/telegram/message")
def telegram_message(m: TelegramMessageIn):
    started_new = insert_message(
        chat_id=m.chat_id,
        text=m.text,
        user_id=m.user_id,
        user_name=m.user_name,
        message_id=m.message_id,
        sent_at=m.sent_at,
    )
    return {"ok": True, "started_new_batch": started_new}


@app.get("/kus")
def get_kus_json():
    project = get_or_create_default_project()
    return list_kus(project_id=project["id"])


@app.post("/debug/finalize_now")
def finalize_now():
    return finalize_due_batches(settings.batch_window_seconds)


@app.get("/favicon.ico")
def favicon():
    # чтобы браузер не спамил 404
    return Response(status_code=204)


# -------------------------
# HTML UI
# -------------------------
def _layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; background:#0b0b0c; color:#eaeaea; margin:0; }}
    a {{ color:#9ad; text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 28px; }}
    .top {{ display:flex; justify-content:space-between; align-items:center; gap:12px; }}
    .card {{ background:#141416; border:1px solid #26262a; border-radius:14px; padding:16px 18px; margin:12px 0; }}
    .muted {{ color:#a6a6ad; font-size: 13px; }}
    h1 {{ margin: 8px 0 18px; font-size: 26px; }}
    h2 {{ margin: 0 0 8px; font-size: 18px; }}
    .pill {{ display:inline-block; padding: 4px 10px; border-radius: 999px; border:1px solid #2a2a30; font-size: 12px; color:#cfcfd6; }}
    ul {{ margin: 8px 0 0 18px; }}
    pre {{ white-space: pre-wrap; background:#0f0f12; border:1px solid #26262a; border-radius:12px; padding:12px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div class="muted">Talkset • SQLite MVP</div>
      <div class="muted"><a href="/docs">API</a> • <a href="/kus">JSON</a> • <a href="/health">Health</a></div>
    </div>
    <h1>{html.escape(title)}</h1>
    {body}
  </div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def home():
    project = get_or_create_default_project()
    kus = list_kus(project_id=project["id"])

    if not kus:
        body = """
        <div class="card">
          <div class="muted">Пока нет ни одного KU.</div>
          <div class="muted">Напиши сообщения в чат → подожди окно батча → обнови страницу.</div>
        </div>
        """
        return _layout("Knowledge Units", body)

    cards = []
    for ku in kus[:80]:
        cid = ku["id"]
        title = html.escape(ku["title"] or "(без названия)")
        ku_type = html.escape(ku["type"])
        status = html.escape(ku["status"])
        summary = html.escape((ku.get("content_ai") or {}).get("summary", "")[:260])

        cards.append(f"""
        <div class="card">
          <div style="display:flex; justify-content:space-between; gap:12px; align-items:flex-start;">
            <div>
              <h2><a href="/ku/{cid}">{title}</a></h2>
              <div class="muted">{summary if summary else "—"}</div>
            </div>
            <div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end;">
              <span class="pill">{ku_type}</span>
              <span class="pill">{status}</span>
            </div>
          </div>
        </div>
        """)

    return _layout("Knowledge Units", "\n".join(cards))


@app.get("/ku/{ku_id}", response_class=HTMLResponse)
def ku_page(ku_id: str):
    ku = get_ku(ku_id)
    if not ku:
        return _layout("KU не найден", f'<div class="card">KU <code>{html.escape(ku_id)}</code> не найден.</div>')

    c = ku.get("content_ai") or {}
    title = ku.get("title", "KU")
    ku_type = ku.get("type", "")
    status = ku.get("status", "")

    def render_list(items):
        if not items:
            return "<div class='muted'>—</div>"
        lis = "".join(f"<li>{html.escape(str(x))}</li>" for x in items)
        return f"<ul>{lis}</ul>"

    body = f"""
    <div class="card">
      <div style="display:flex; justify-content:space-between; gap:12px; align-items:flex-start;">
        <div>
          <div class="muted"><a href="/">← назад</a></div>
          <h2 style="margin-top:8px;">{html.escape(title)}</h2>
          <div class="muted">{html.escape(ku_id)}</div>
        </div>
        <div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end;">
          <span class="pill">{html.escape(ku_type)}</span>
          <span class="pill">{html.escape(status)}</span>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>Summary</h2>
      <div>{html.escape(c.get("summary","") or "—")}</div>
    </div>

    <div class="card">
      <h2>Decisions</h2>
      {render_list(c.get("decisions", []))}
    </div>

    <div class="card">
      <h2>Open questions</h2>
      {render_list(c.get("open_questions", []))}
    </div>

    <div class="card">
      <h2>Next steps</h2>
      {render_list(c.get("next_steps", []))}
    </div>

    <div class="card">
      <h2>Notes</h2>
      {render_list(c.get("notes", []))}
    </div>
    """

    return _layout(title, body)
