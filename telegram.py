from __future__ import annotations

import asyncio
import os

import httpx

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")


async def send_message(chat_id: int, html_text: str, button: tuple[str, str] | None = None) -> None:
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не задан в .env")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    body = {
        "chat_id": chat_id,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if button:
        body["reply_markup"] = {"inline_keyboard": [[{"text": button[0], "url": button[1]}]]}

    last_error: Exception | None = None
    for attempt in range(3):   
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(url, json=body)
            if r.status_code == 200:
                return
            # 4xx (кроме 429) — ошибка запроса (плохой chat_id/текст), повтор не поможет
            if 400 <= r.status_code < 500 and r.status_code != 429:
                raise RuntimeError(f"Telegram {r.status_code}: {r.text}")
            last_error = RuntimeError(f"Telegram {r.status_code}: {r.text}")
        except httpx.HTTPError as error:   # таймаут/обрыв — повторяем
            last_error = error
        await asyncio.sleep(1 + attempt)

    raise last_error or RuntimeError("Telegram: не удалось отправить после повторов")
