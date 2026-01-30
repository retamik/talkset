import json
import time
import re
from uuid import uuid4
from typing import Optional, Dict, Any, List

from backend.db import get_conn
from backend.llm_client import decide_ku_action, update_ku_content, select_relevant
from backend.models import KUContent


def now_ts() -> int:
    return int(time.time())


# Text sanitizing (убираем ненужное/управляющие символы)
_BAD_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")

def sanitize_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\uFFFD", "")
    s = _BAD_CHARS_RE.sub("", s)
    s = s.replace("\\\\", "\\")
    s = s.replace("\r", " ").replace("\t", " ")
    s = _MULTI_SPACE_RE.sub(" ", s).strip()
    return s


# Projects
def get_or_create_default_project() -> Dict[str, Any]:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM projects WHERE id = ?", ("default",))
    row = cur.fetchone()

    if row:
        conn.close()
        return dict(row)

    cur.execute(
        "INSERT INTO projects (id, name, short_context, project_summary, status) VALUES (?, ?, ?, ?, ?)",
        ("default", "Default project", "Auto-created", "", "active")
    )
    conn.commit()
    conn.close()
    return {"id": "default", "name": "Default project", "short_context": "Auto-created"}


# -------------------------
# Messages / batching
# -------------------------
def insert_message(chat_id: str, text: str,
                   user_id: Optional[str], user_name: Optional[str],
                   message_id: Optional[str], sent_at: Optional[int]) -> bool:
    """
    Returns True if this message started a new batch window for this chat.
    """
    conn = get_conn()
    cur = conn.cursor()

    created_at = now_ts()
    text = sanitize_text(text or "")

    cur.execute("""
      INSERT INTO messages (chat_id, user_id, user_name, message_id, sent_at, text, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (chat_id, user_id, user_name, message_id, sent_at, text, created_at))

    cur.execute("SELECT started_at FROM open_batches WHERE chat_id = ?", (chat_id,))
    row = cur.fetchone()

    if row is None:
        cur.execute("INSERT INTO open_batches (chat_id, started_at) VALUES (?, ?)", (chat_id, created_at))
        started_new = True
    else:
        started_new = False

    conn.commit()
    conn.close()
    return started_new


# -------------------------
# KU read/list
# -------------------------
def list_kus(project_id: str) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      SELECT * FROM kus
      WHERE project_id = ?
      ORDER BY last_activity_at DESC
    """, (project_id,))
    rows = cur.fetchall()
    conn.close()

    out = []
    for r in rows:
        d = dict(r)
        d["content_ai"] = json.loads(d["content_ai_json"])
        del d["content_ai_json"]
        out.append(d)
    return out


def get_ku(ku_id: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM kus WHERE id = ? LIMIT 1", (ku_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["content_ai"] = json.loads(d["content_ai_json"])
    del d["content_ai_json"]
    return d


def _active_kus_brief(project_id: str) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      SELECT id, title, type, status
      FROM kus
      WHERE project_id = ? AND status = 'Active'
      ORDER BY last_activity_at DESC
    """, (project_id,))
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _create_ku(project_id: str, title: str, ku_type: str) -> str:
    ku_id = str(uuid4())
    ts = now_ts()
    content_ai = KUContent().model_dump()

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      INSERT INTO kus (id, project_id, type, title, status, content_ai_json, content_human, created_at, last_activity_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ku_id, project_id, ku_type, sanitize_text(title)[:120] or "Тема",
        "Active",
        json.dumps(content_ai, ensure_ascii=False),
        "",
        ts,
        ts
    ))
    conn.commit()
    conn.close()
    return ku_id


def _ku_exists(ku_id: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM kus WHERE id = ? LIMIT 1", (ku_id,))
    ok = cur.fetchone() is not None
    conn.close()
    return ok


def _update_ku_ai(ku_id: str, batch_text: str) -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT content_ai_json FROM kus WHERE id = ?", (ku_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return

    existing = json.loads(row["content_ai_json"])
    updated = update_ku_content(existing, batch_text)

    if "_error" in updated:
        existing.setdefault("notes", []).append(f"LLM error: {updated.get('_error')}")
        new_content = existing
    else:
        # fallback если summary пустой
        if not (updated.get("summary") or "").strip():
            updated["summary"] = sanitize_text(batch_text.splitlines()[0])[:200]
        new_content = KUContent(**updated).model_dump()

    cur.execute("""
      UPDATE kus
      SET content_ai_json = ?, last_activity_at = ?
      WHERE id = ?
    """, (json.dumps(new_content, ensure_ascii=False), now_ts(), ku_id))

    conn.commit()
    conn.close()


def _append_note_to_ku(ku_id: str, note: str) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT content_ai_json FROM kus WHERE id = ?", (ku_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    content = json.loads(row["content_ai_json"])
    content.setdefault("notes", []).append(sanitize_text(note))
    cur.execute(
        "UPDATE kus SET content_ai_json=?, last_activity_at=? WHERE id=?",
        (json.dumps(content, ensure_ascii=False), now_ts(), ku_id)
    )
    conn.commit()
    conn.close()


def process_batch(project_id: str, batch_text: str) -> Dict[str, str]:
    active = _active_kus_brief(project_id)
    decision = decide_ku_action(batch_text, active)

    if decision.get("_error"):
        ku_id = _create_ku(project_id, "Батч (auto)", "Discussion")
        _update_ku_ai(ku_id, batch_text)
        return {"action": "create_ku_fallback", "ku_id": ku_id}

    action = decision.get("action", "noop")

    # Guardrail: update без target -> create
    if action == "update_ku" and not decision.get("target_ku_id"):
        action = "create_ku"

    if action == "noop":
        return {"action": "noop", "ku_id": ""}

    if action == "create_ku":
        new_ku = decision.get("new_ku") or {}
        title = (new_ku.get("title") or "Тема").strip()
        ku_type = (new_ku.get("type") or "Discussion").strip()
        ku_id = _create_ku(project_id, title, ku_type)
        _update_ku_ai(ku_id, batch_text)
        return {"action": "create_ku", "ku_id": ku_id}

    if action == "update_ku":
        target = decision.get("target_ku_id")
        if target and _ku_exists(target):
            _update_ku_ai(target, batch_text)
            return {"action": "update_ku", "ku_id": target}

        ku_id = _create_ku(project_id, "Батч (auto)", "Discussion")
        _update_ku_ai(ku_id, batch_text)
        return {"action": "update_missing_fallback", "ku_id": ku_id}

    ku_id = _create_ku(project_id, "Батч (auto)", "Discussion")
    _update_ku_ai(ku_id, batch_text)
    return {"action": "unknown_fallback", "ku_id": ku_id}


def finalize_due_batches(batch_window_seconds: int) -> List[Dict[str, Any]]:
    """
    Закрывает батчи по таймеру.
    Делает AI-фильтр и разбивает батч на topics → по каждой теме создаёт/обновляет KU.
    """
    project = get_or_create_default_project()
    project_id = project["id"]

    conn = get_conn()
    cur = conn.cursor()

    now = now_ts()
    cur.execute("SELECT chat_id, started_at FROM open_batches")
    batches = cur.fetchall()

    results: List[Dict[str, Any]] = []

    for b in batches:
        chat_id = b["chat_id"]
        started_at = b["started_at"]

        if now - started_at < batch_window_seconds:
            continue

        cur.execute("""
          SELECT user_name, user_id, text, created_at
          FROM messages
          WHERE chat_id = ? AND created_at >= ?
          ORDER BY created_at ASC
        """, (chat_id, started_at))
        msgs = cur.fetchall()

        # закрываем батч сразу
        cur.execute("DELETE FROM open_batches WHERE chat_id = ?", (chat_id,))
        conn.commit()

        # собираем сырой батч
        lines = []
        for m in msgs:
            user = m["user_name"] or m["user_id"] or "user"
            text = sanitize_text((m["text"] or "").strip())
            if not text:
                continue
            lines.append(f"{user}: {text}")
        raw_text = "\n".join(lines).strip()

        if not raw_text:
            results.append({"chat_id": chat_id, "status": "empty_batch", "messages": len(msgs)})
            continue

        # ограничение на размер
        MAX_CHARS = 12000
        if len(raw_text) > MAX_CHARS:
            raw_text = raw_text[:MAX_CHARS] + "\n[...обрезано...]"

        conn.close()
        try:
            # 1) AI-фильтр + темы
            sel = select_relevant(raw_text)

            if sel.get("_error"):
                topics = [{"title": "Батч", "type": "Discussion", "cleaned_text": raw_text}]
                drop_count = None
                note = f"AI-фильтр упал: {sel.get('_error')}"
            else:
                topics = sel.get("topics") or []
                drop_count = sel.get("drop_count")
                note = sel.get("notes") or ""

            if not topics:
                results.append({"chat_id": chat_id, "status": "empty_after_ai_filter", "messages": len(msgs)})
                continue

            pipelines = []
            for t in topics:
                title = sanitize_text((t.get("title") or "Тема").strip())[:120]
                ku_type = (t.get("type") or "Discussion").strip()
                cleaned = sanitize_text((t.get("cleaned_text") or "").strip())

                if not cleaned:
                    continue

                # подсказка модели про тему
                decorated = f"[ТЕМА: {title}]\n{cleaned}"

                p = process_batch(project_id, decorated)
                pipelines.append({"topic": title, "pipeline": p})

                ku_id = p.get("ku_id")
                if ku_id:
                    if drop_count is not None:
                        _append_note_to_ku(ku_id, f"AI-фильтр: удалено ~{drop_count} строк шума (на батч).")
                    if note:
                        _append_note_to_ku(ku_id, f"AI-фильтр note: {note}")

            results.append({"chat_id": chat_id, "status": "processed", "pipelines": pipelines, "messages": len(msgs)})

        except Exception as e:
            results.append({"chat_id": chat_id, "status": "error", "error": str(e)})
        finally:
            conn = get_conn()
            cur = conn.cursor()

    conn.close()
    return results
