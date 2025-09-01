from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse
import httpx
from app.config import settings
from app.db.mongo import test, conversations, users

print(f"[STARTUP] Запуск WhatsApp FastAPI Bot")
print(f"[STARTUP] Настройки:")
print(f"[STARTUP] - VERSION: {settings.VERSION}")
print(f"[STARTUP] - PHONE_NUMBER_ID: {settings.PHONE_NUMBER_ID}")
print(f"[STARTUP] - VERIFY_TOKEN: {settings.VERIFY_TOKEN}")
print(f"[STARTUP] - ACCESS_TOKEN: {'*' * (len(settings.ACCESS_TOKEN)-4) + settings.ACCESS_TOKEN[-4:] if len(settings.ACCESS_TOKEN) > 4 else '***'}")
print(f"[STARTUP] - MONGO_URI: {settings.MONGO_URI}")
print(f"[STARTUP] - MONGO_DB: {settings.MONGO_DB}")

app = FastAPI(title="WhatsApp FastAPI Bot")

GRAPH_BASE = f"https://graph.facebook.com/{settings.VERSION}"
print(f"[STARTUP] Graph API Base URL: {GRAPH_BASE}")

async def send_whatsapp_text(recipient_waid: str, text: str) -> dict:
    """
    Отправка текстового сообщения пользователю в WhatsApp Cloud API.
    recipient_waid — номер в формате международном (например '9725....' без +)
    Либо можно передавать E.164, но Cloud API ожидает 'to' как wa_id (обычно без '+').
    """
    print(f"[SEND_MSG] Отправляем сообщение пользователю {recipient_waid}: {text}")
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
    print(f"[SEND_MSG] URL: {url}")
    print(f"[SEND_MSG] Headers: {headers}")
    print(f"[SEND_MSG] Payload: {payload}")
    
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            r = await client.post(url, headers=headers, json=payload)
            print(f"[SEND_MSG] Response status: {r.status_code}")
            print(f"[SEND_MSG] Response body: {r.text}")
            r.raise_for_status()
            result = r.json()
            print(f"[SEND_MSG] Успешно отправлено: {result}")
            return result
        except Exception as e:
            print(f"[SEND_MSG] ОШИБКА при отправке: {e}")
            raise

@app.get("/health", response_class=PlainTextResponse)
async def health():
    return "ok\n"

# --- Webhook verification (Meta -> GET) ---
@app.get("/webhook")
async def verify_webhook(request: Request):
    """
    Meta вызовет этот GET при настройке вебхука.
    Нужно вернуть hub.challenge, если VERIFY_TOKEN совпал.
    """
    print(f"[WEBHOOK_VERIFY] Получен запрос на верификацию webhook")
    params = dict(request.query_params)
    print(f"[WEBHOOK_VERIFY] Параметры запроса: {params}")
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == settings.VERIFY_TOKEN and challenge:
        print(f"[WEBHOOK_VERIFY] Верификация успешна, возвращаем challenge: {challenge}")
        return PlainTextResponse(challenge, status_code=200)
    
    print(f"[WEBHOOK_VERIFY] ОШИБКА верификации: mode={mode}, token={token}, expected_token={settings.VERIFY_TOKEN}, challenge={challenge}")
    raise HTTPException(status_code=403, detail="Verification failed")

# --- Webhook receiver (Meta -> POST) ---
@app.post("/webhook")
async def whatsapp_webhook(body: dict):
    """
    Тут прилетают апдейты от Meta.
    Сценарий:
      1) Извлекаем сообщение (текст и отправителя).
      2) Сохраняем в Mongo (conversations, users).
      3) Отвечаем пользователю эхо-сообщением.
    """
    print(f"[WEBHOOK] Получен webhook от WhatsApp: {body}")
    
    # Сохраняем «как есть» для отладки
    try:
        conversations.insert_one({"direction": "INCOMING_RAW", "body": body})
        print(f"[WEBHOOK] Сохранили raw данные в MongoDB")
    except Exception as e:
        print(f"[WEBHOOK] ОШИБКА сохранения в MongoDB: {e}")

    try:
        print(f"[WEBHOOK] Начинаем обработку webhook")
        entry = body.get("entry", [])[0]
        print(f"[WEBHOOK] Entry: {entry}")
        changes = entry.get("changes", [])[0]
        print(f"[WEBHOOK] Changes: {changes}")
        value = changes.get("value", {})
        print(f"[WEBHOOK] Value: {value}")
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])
        print(f"[WEBHOOK] Messages: {messages}")
        print(f"[WEBHOOK] Contacts: {contacts}")

        if not messages:
            # Может прилетать status/ack без messages — просто подтверждаем.
            print(f"[WEBHOOK] Нет сообщений в webhook, возможно это статус или подтверждение")
            return JSONResponse({"status": "no_message"}, status_code=200)

        msg = messages[0]
        msg_type = msg.get("type")
        from_user = msg.get("from")  # wa_id отправителя (обычно без '+')
        text_body = None
        
        print(f"[WEBHOOK] Обрабатываем сообщение: type={msg_type}, from={from_user}")
        print(f"[WEBHOOK] Полное сообщение: {msg}")

        if msg_type == "text":
            text_body = msg.get("text", {}).get("body")
            print(f"[WEBHOOK] Текстовое сообщение: {text_body}")
        elif msg_type == "button":
            text_body = msg.get("button", {}).get("text")
            print(f"[WEBHOOK] Кнопка: {text_body}")
        elif msg_type == "interactive":
            # Пример: reply/ list_reply
            interactive = msg.get("interactive", {})
            if "button_reply" in interactive:
                text_body = interactive["button_reply"].get("title")
            elif "list_reply" in interactive:
                text_body = interactive["list_reply"].get("title")
            print(f"[WEBHOOK] Интерактивное сообщение: {text_body}")
        else:
            print(f"[WEBHOOK] Неизвестный тип сообщения: {msg_type}")

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
            print(f"[WEBHOOK] Обновляем информацию о пользователе: {from_user}")
            print(f"[WEBHOOK] User info: {user_info}")
            try:
                users.update_one(
                    {"wa_id": from_user},
                    {"$set": {"wa_id": from_user, **({k: v for k, v in user_info.items() if v})}},
                    upsert=True,
                )
                print(f"[WEBHOOK] Пользователь сохранен в MongoDB")
            except Exception as e:
                print(f"[WEBHOOK] ОШИБКА сохранения пользователя: {e}")

        try:
            conversations.insert_one(
                {
                    "direction": "IN",
                    "from": from_user,
                    "type": msg_type,
                    "text": text_body,
                    "raw": msg,
                }
            )
            print(f"[WEBHOOK] Входящее сообщение сохранено в MongoDB")
        except Exception as e:
            print(f"[WEBHOOK] ОШИБКА сохранения сообщения: {e}")

        # Формируем ответ (эхо)
        reply_text = "✅ Получил: " + (text_body or "(не текст)")
        print(f"[WEBHOOK] Формируем ответ: {reply_text}")
        
        if from_user:
            print(f"[WEBHOOK] Отправляем ответ пользователю {from_user}")
            try:
                await send_whatsapp_text(from_user, reply_text)
                print(f"[WEBHOOK] Ответ отправлен успешно")
                
                conversations.insert_one(
                    {
                        "direction": "OUT",
                        "to": from_user,
                        "type": "text",
                        "text": reply_text,
                    }
                )
                print(f"[WEBHOOK] Исходящее сообщение сохранено в MongoDB")
            except Exception as send_error:
                print(f"[WEBHOOK] ОШИБКА отправки ответа: {send_error}")
        else:
            print(f"[WEBHOOK] Нет from_user, не можем отправить ответ")

        print(f"[WEBHOOK] Обработка завершена успешно")
        return JSONResponse({"status": "ok"}, status_code=200)

    except Exception as e:
        print(f"[WEBHOOK] КРИТИЧЕСКАЯ ОШИБКА: {e}")
        print(f"[WEBHOOK] Тип ошибки: {type(e).__name__}")
        import traceback
        print(f"[WEBHOOK] Traceback: {traceback.format_exc()}")
        
        try:
            conversations.insert_one({"direction": "ERROR", "error": str(e), "body": body})
            print(f"[WEBHOOK] Ошибка сохранена в MongoDB")
        except Exception as db_error:
            print(f"[WEBHOOK] ОШИБКА сохранения ошибки в MongoDB: {db_error}")
        
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
