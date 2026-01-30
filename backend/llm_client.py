import json
import httpx
from typing import Any, Dict, List
from config import settings

PROXYAPI_URL = "https://api.proxyapi.ru/openai/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def _base_url() -> str:
    if (settings.llm_provider or "").lower() == "openai":
        return OPENAI_URL
    return PROXYAPI_URL


def _headers() -> Dict[str, str]:
    provider = (settings.llm_provider or "").lower()

    if provider == "proxyapi":
        if not getattr(settings, "proxyapi_api_key", None):
            raise RuntimeError("PROXYAPI_API_KEY не задан в .env")
        return {"Authorization": f"Bearer {settings.proxyapi_api_key}", "Content-Type": "application/json"}

    if provider == "openai":
        if not getattr(settings, "openai_api_key", None):
            raise RuntimeError("OPENAI_API_KEY не задан в .env")
        return {"Authorization": f"Bearer {settings.openai_api_key}", "Content-Type": "application/json"}

    raise RuntimeError("LLM_PROVIDER должен быть proxyapi или openai")


def _strip_code_fence(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s.replace("json", "", 1).strip()
    return s.strip()


def chat_json(system: str, user: str, schema_hint: str, temperature: float = 0.0) -> Dict[str, Any]:
    prompt = (
        f"{user}\n\n"
        f"Верни ОДИН JSON-объект строго по схеме:\n{schema_hint}\n"
        f"Требования:\n"
        f"- Только JSON, без markdown и без комментариев\n"
        f"- Никаких '```'\n"
        f"- Никаких лишних ключей\n"
    )

    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
    }

    with httpx.Client(timeout=60) as client:
        resp = client.post(_base_url(), headers=_headers(), json=payload)
        resp.raise_for_status()
        data = resp.json()

    raw = _strip_code_fence(data["choices"][0]["message"]["content"])

    try:
        return json.loads(raw)
    except Exception as e:
        return {"_error": f"json_parse_failed: {e}", "raw": raw}


# -------------------------
# 1) AI-фильтр + темы (topics)
# -------------------------
def select_relevant(batch_text: str) -> Dict[str, Any]:
    schema = """{
      "topics": [
        {
          "title": string,
          "type": "Discussion"|"Decision"|"Hypothesis"|"Note",
          "cleaned_text": string
        }
      ],
      "drop_count": number,
      "notes": string
    }"""

    user = f"""Есть батч сообщений. Сформируй темы для базы знаний.

Шаг 1 — УДАЛИ шум:
- приветствия/реакции/эмодзи/односложные ответы ("ок/ага/угу/спс/лол")
- тестовый мусор ("qwe", "123", "asdf"), бессмысленные строки
- мат и оскорбления: вырезай целиком (не заменяй звёздочками)
- повторы без новой информации

Шаг 2 — Разбей оставшееся по ТЕМАМ.
Если в батче несколько разных тем (созвон, уборка, проверка, и т.д.) — делай несколько topics.

Шаг 3 — Для каждой темы:
- title: коротко, по-русски, 3–8 слов
- type:
  - Decision если это по сути объявление/распоряжение/договорённость
  - Note если это важный факт/событие
  - Discussion если это обсуждение
- cleaned_text: только релевантные реплики по теме

Важно:
- Если полезного нет — topics=[]
- cleaned_text должен быть коротким и чистым

Батч:
{batch_text}
"""
    return chat_json(
        system="Ты чистишь чат от мусора и группируешь по темам для базы знаний.",
        user=user,
        schema_hint=schema,
        temperature=0.0,
    )


# -------------------------
# 2) Решить: обновить существующий KU или создать новый
# -------------------------
def decide_ku_action(batch_text: str, active_kus: list) -> Dict[str, Any]:
    schema = """{
      "action": "update_ku" | "create_ku" | "noop",
      "target_ku_id": string | null,
      "new_ku": { "title": string, "type": "Discussion"|"Decision"|"Hypothesis"|"Note" } | null,
      "reason": string
    }"""

    kus_lines = "\n".join(
        [f"- {k['id']} | {k['title']} | {k['type']} | {k['status']}" for k in active_kus]
    ) or "(пусто)"

    user = f"""Текст (уже очищенный, одна тема):
{batch_text}

Активные KU:
{kus_lines}

Выбор:
- update_ku: если тема явно продолжает существующий KU
- create_ku: если тема новая
- noop: если нет полезной информации

Важно:
- update_ku нельзя возвращать без target_ku_id
"""

    return chat_json(
        system="Ты маршрутизируешь темы чата в KU: обновить существующий или создать новый.",
        user=user,
        schema_hint=schema,
        temperature=0.0,
    )


# -------------------------
# 3) Обновить KU контент, учитывая переносы/конфликты
# -------------------------
def update_ku_content(existing_content: Dict[str, Any], batch_text: str) -> Dict[str, Any]:
    schema = """{
      "summary": string,
      "decisions": [string],
      "open_questions": [string],
      "next_steps": [string],
      "notes": [string]
    }"""

    user = f"""Текущий AI-контент KU (JSON):
{json.dumps(existing_content, ensure_ascii=False)}

Новые сообщения по этой теме:
{batch_text}

Твоя задача — обновить KU.

Правила извлечения:
1) DECISIONS:
- Считай решениями не только фразы со словом "решили",
  но и любые ДОГОВОРЁННОСТИ и распоряжения:
  - время/дата/место ("созвон в 15:00", "перенесли на завтра", "в 6 утра приедут")
  - обязательные указания ("надо освободить точки", "всем быть", "сделать до...")
- Формулируй решения кратко, по-русски, без мата.

2) OPEN_QUESTIONS:
- Любые вопросы без ответа (в т.ч. "во сколько удобно", "когда можем", "кто возьмёт")
- Даже если нет знака "?"

3) NEXT_STEPS:
- Конкретные действия, особенно если есть "надо/нужно/сделайте"
- Если из решения следует действие — тоже добавь

4) ПРОТИВОРЕЧИЯ / ПЕРЕНОСЫ (самое важное):
Если есть несколько конфликтующих договорённостей (например: 15:00 → потом 16:00 → потом на другой день 15:00),
то:
- В SUMMARY и DECISIONS оставь АКТУАЛЬНОЕ (последнее по смыслу)
- Предыдущие варианты не теряй: добавь в NOTES как историю изменений
  форматом: "История: было X → стало Y → перенесено на Z"

5) SUMMARY:
- 1–3 предложения, описывает текущий статус темы
- Должно отражать актуальное время/дату, если это ключевое

6) ЧИСТОТА:
- Не добавляй мат/оскорбления
- Не добавляй мусорные строки

Верни JSON строго по схеме.
"""

    return chat_json(
        system="Ты ведёшь KU как живой документ: фиксируешь решения, вопросы, действия и историю переносов.",
        user=user,
        schema_hint=schema,
        temperature=0.2,
    )
