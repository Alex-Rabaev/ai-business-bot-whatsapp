from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse
import httpx
from app.config import settings
from app.db.mongo import test, conversations, users

app = FastAPI(title="WhatsApp FastAPI Bot")

GRAPH_BASE = f"https://graph.facebook.com/{settings.VERSION}"

async def send_whatsapp_text(recipient_waid: str, text: str) -> dict:
    """
    Отправка текстового сообщения пользователю в WhatsApp Cloud API.
    recipient_waid — номер в формате международном (например '9725....' без +)
    Либо можно передавать E.164, но Cloud API ожидает 'to' как wa_id (обычно без '+').
    """
    url = f"{GRAPH_BASE}/{settings.PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {settings.ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_waid,
        "type": "text",
        "text": {"body": text},
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()

@app.get("/health", response_class=PlainTextResponse)
async def health():
    return "ok"

# --- Webhook verification (Meta -> GET) ---
@app.get("/webhook/whatsapp")
async def verify_webhook(request: Request):
    """
    Meta вызовет этот GET при настройке вебхука.
    Нужно вернуть hub.challenge, если VERIFY_TOKEN совпал.
    """
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == settings.VERIFY_TOKEN and challenge:
        return PlainTextResponse(challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Verification failed")

# --- Webhook receiver (Meta -> POST) ---
@app.post("/webhook/whatsapp")
async def whatsapp_webhook(body: dict):
    """
    Тут прилетают апдейты от Meta.
    Сценарий:
      1) Извлекаем сообщение (текст и отправителя).
      2) Сохраняем в Mongo (conversations, users).
      3) Отвечаем пользователю эхо-сообщением.
    """
    # Сохраняем «как есть» для отладки
    conversations.insert_one({"direction": "INCOMING_RAW", "body": body})

    try:
        entry = body.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])

        if not messages:
            # Может прилетать status/ack без messages — просто подтверждаем.
            return JSONResponse({"status": "no_message"}, status_code=200)

        msg = messages[0]
        msg_type = msg.get("type")
        from_user = msg.get("from")  # wa_id отправителя (обычно без '+')
        text_body = None

        if msg_type == "text":
            text_body = msg.get("text", {}).get("body")
        elif msg_type == "button":
            text_body = msg.get("button", {}).get("text")
        elif msg_type == "interactive":
            # Пример: reply/ list_reply
            interactive = msg.get("interactive", {})
            if "button_reply" in interactive:
                text_body = interactive["button_reply"].get("title")
            elif "list_reply" in interactive:
                text_body = interactive["list_reply"].get("title")

        # user_info из contacts (если есть)
        user_info = {}
        if contacts:
            c = contacts[0]
            user_info = {
                "wa_id": c.get("wa_id"),
                "profile_name": (c.get("profile") or {}).get("name"),
            }

        # Сохраняем в Mongo
        if from_user:
            users.update_one(
                {"wa_id": from_user},
                {"$set": {"wa_id": from_user, **({k: v for k, v in user_info.items() if v})}},
                upsert=True,
            )

        conversations.insert_one(
            {
                "direction": "IN",
                "from": from_user,
                "type": msg_type,
                "text": text_body,
                "raw": msg,
            }
        )

        # Формируем ответ (эхо)
        reply_text = "✅ Получил: " + (text_body or "(не текст)")
        if from_user:
            await send_whatsapp_text(from_user, reply_text)
            conversations.insert_one(
                {
                    "direction": "OUT",
                    "to": from_user,
                    "type": "text",
                    "text": reply_text,
                }
            )

        return JSONResponse({"status": "ok"}, status_code=200)

    except Exception as e:
        conversations.insert_one({"direction": "ERROR", "error": str(e), "body": body})
        # Чтобы Meta перестала ретраить, лучше вернуть 200, но логировать ошибку.
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=200)

# --- Простой тест Mongo: вставка в test коллекцию ---
@app.post("/test/mongo")
async def test_mongo(payload: dict):
    """
    Пример запроса:
    POST /test/mongo
    {
      "message": "hello",
      "user": {"id": 123, "name": "Alex"}
    }
    """
    doc = {
        "message": payload.get("message"),
        "user": payload.get("user"),
    }
    res = test.insert_one(doc)
    return {"inserted_id": str(res.inserted_id)}
