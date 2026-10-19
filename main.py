"""OpenFlux × Bedolaga мост.

Отдельный сервис рядом с ботом (не форк):
  /webhook   — на покупку FULL шлёт юзеру поздравление с ссылкой (через API Bedolaga).
  /connect   — страница-гайд (установить приложение + подключить).
  /api/*      — создать канал и опрашивать статус.
  фон        — крон-сверка: удаляет каналы юзеров без активной FULL-подписки.

Запуск:  uvicorn main:app --port 8000
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import bedolaga
import provisioner
import reconcile
import telegram
import tokens

BASE = Path(__file__).parent
WEBHOOK_SECRET = os.getenv("BEDOLAGA_WEBHOOK_SECRET", "")
BRIDGE_PUBLIC_URL = os.getenv("BRIDGE_PUBLIC_URL", "http://localhost:8000").rstrip("/")
# Набор сквадов, которые вместе означают тариф FULL (через запятую в .env)
FULL_SQUADS = {s.strip() for s in os.getenv("FULL_SQUADS", "").split(",") if s.strip()}
# Клиентские приложения для страницы /connect
APK_URL_ANDROID = os.getenv("APK_URL_ANDROID", "").strip()     # внешний fallback, если локального apk нет
TESTFLIGHT_URL_IOS = os.getenv("TESTFLIGHT_URL_IOS", "").strip()
APK_LOCAL = BASE / "apk" / "openflux-android.apk"              # самохостинг apk (монтируется в контейнер)
# Текст поздравления и подпись кнопки (переопределяются в .env; \n в значении = перенос строки)
CONGRATS_MESSAGE = os.getenv(
    "CONGRATS_MESSAGE",
    "🐋 <b>Поздравляем с тарифом FULL!</b>\n\nВам доступен дополнительный обход белых списков.",
).replace("\\n", "\n")
CONGRATS_BUTTON = os.getenv("CONGRATS_BUTTON", "Подключить обход →")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(reconcile.loop())   # крон-сверка в фоне
    yield
    task.cancel()


app = FastAPI(title="OpenFlux × Bedolaga bridge", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")


@app.get("/connect", response_class=HTMLResponse)
async def connect_page() -> str:
    return (BASE / "static" / "connect.html").read_text(encoding="utf-8")


@app.get("/download/android")
async def download_android():
    """Прямая отдача apk (самохостинг). Нет локального файла → редирект на внешний URL."""
    if APK_LOCAL.exists():
        return FileResponse(
            APK_LOCAL,
            media_type="application/vnd.android.package-archive",
            filename="openflux-android.apk",
        )
    if APK_URL_ANDROID:
        return RedirectResponse(APK_URL_ANDROID, status_code=302)
    raise HTTPException(status_code=503, detail="APK недоступен")


@app.get("/api/links")
async def api_links() -> dict:
    """Ссылки на приложения для страницы (всё из конфига, страница остаётся статикой)."""
    return {"android": "/download/android", "ios": TESTFLIGHT_URL_IOS}


@app.post("/api/provision")
async def api_provision(token: str) -> dict:
    # Авторизация по подписанному токену (id в ссылке подделать нельзя) + свежая
    # проверка подписки: иначе любой перебором user_id штамповал бы каналы.
    user_id = tokens.verify(token)
    if user_id is None:
        raise HTTPException(status_code=403, detail="Ссылка недействительна или устарела")
    if FULL_SQUADS and not await bedolaga.is_full_active(user_id, FULL_SQUADS):
        raise HTTPException(status_code=403, detail="Активная подписка FULL не найдена")
    return {"job_id": await provisioner.start(str(user_id))}


@app.get("/api/status")
async def api_status(job_id: str) -> dict:
    job = provisioner.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    raw = await request.body()
    event = request.headers.get("X-Webhook-Event", "")
    signature = request.headers.get("X-Webhook-Signature", "")
    if WEBHOOK_SECRET and not _verify(raw, signature):
        raise HTTPException(status_code=401, detail="bad signature")
    payload = json.loads(raw or b"{}")
    # Покупка подписки → поздравить. Отвечаем вебхуку сразу, сообщение шлём
    # в фоне, чтобы не держать доставку Bedolaga (у неё свои таймауты).
    if event == "transaction.created" and "subscription" in str(payload.get("type", "")).lower():
        asyncio.create_task(_on_purchase(payload))
    return {"ok": True}


async def _on_purchase(payload: dict) -> None:
    try:
        user_id = int(payload["user_id"])
        # если набор сквадов FULL задан — убедиться, что это именно FULL, а не другой тариф
        if FULL_SQUADS and not await bedolaga.is_full_active(user_id, FULL_SQUADS):
            return
        chat_id = await bedolaga.get_telegram_id(user_id)
        print(f"[purchase] user_id={user_id} → chat_id={chat_id}", flush=True)
        if not chat_id:
            return
        link = f"{BRIDGE_PUBLIC_URL}/connect?token={tokens.make(user_id)}"
        await telegram.send_message(chat_id, CONGRATS_MESSAGE, button=(CONGRATS_BUTTON, link))
        print(f"[purchase] поздравление отправлено user_id={user_id} chat_id={chat_id}", flush=True)
    except Exception as error:   # noqa: BLE001
        print(f"[purchase] ошибка: {type(error).__name__}: {error}", flush=True)


def _verify(raw: bytes, signature: str) -> bool:
    # Bedolaga подписывает РОВНО те байты, что шлёт телом: hmac-sha256 над строкой
    # json.dumps(payload, ensure_ascii=False), которая и уходит как data=.
    # Поэтому проверяем raw как есть — без пере-сериализации (иначе подпись не сойдётся).
    expected = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    got = signature.replace("sha256=", "", 1).strip()
    return hmac.compare_digest(expected, got)


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "provision": "stub" if provisioner.STUB else "real",
        "reconcile": reconcile.MODE,
    }
