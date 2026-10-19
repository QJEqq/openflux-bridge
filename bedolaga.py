"""Клиент к REST API Bedolaga.

Мост только читает подписки и просит бота отправить сообщение — в чужую БД не лезем.
Авторизация: Bearer-токен (создаётся в Bedolaga, кладётся в .env).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

API_URL = os.getenv("BEDOLAGA_API_URL", "http://localhost:8080").rstrip("/")
API_TOKEN = os.getenv("BEDOLAGA_API_TOKEN", "")


def _headers() -> dict:
    return {"Authorization": f"Bearer {API_TOKEN}"}


async def get_telegram_id(user_id: int) -> int | None:
    """Внутренний user_id → telegram_id (chat_id для отправки).

    Через список: на этой версии /users/{X} трактует путь как telegram_id,
    поэтому по внутреннему id напрямую не спросить — ищем в списке.
    """
    offset = 0
    async with httpx.AsyncClient(timeout=15) as client:
        while True:
            r = await client.get(
                f"{API_URL}/users",
                params={"limit": 200, "offset": offset},
                headers=_headers(),
            )
            r.raise_for_status()
            data = r.json()
            items = data["items"] if isinstance(data, dict) and "items" in data else data
            for u in items:
                if u.get("id") == user_id:
                    return u.get("telegram_id")
            if len(items) < 200:
                return None
            offset += 200


def _is_active(sub: dict) -> bool:
    # Без угадывания enum статусов: активна, если срок ещё не вышел.
    raw = sub.get("end_date")
    if not raw:
        return False
    end = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return end > datetime.now(timezone.utc)


def _is_full(sub: dict, full_squads: set[str]) -> bool:
    # FULL = подписка содержит ВСЕ сквады набора FULL. Пустой набор = любая подписка.
    if not full_squads:
        return True
    return full_squads.issubset(set(sub.get("connected_squads") or []))


def _eligible(sub: dict, full_squads: set[str]) -> bool:
    """Право на доп. обход: активна + НЕ триал + это FULL."""
    return _is_active(sub) and not sub.get("is_trial") and _is_full(sub, full_squads)


async def is_full_active(user_id: int, full_squads: set[str]) -> bool:
    """Есть ли у юзера активная FULL-подписка (проверка после покупки)."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{API_URL}/subscriptions",
            params={"user_id": user_id, "limit": 200},
            headers=_headers(),
        )
        r.raise_for_status()
        subs = r.json()
    return any(_eligible(s, full_squads) for s in subs)


async def active_full_user_ids(full_squads: set[str]) -> set[int]:
    """Множество user_id с активной FULL-подпиской (для сверки в кроне)."""
    ids: set[int] = set()
    offset = 0
    async with httpx.AsyncClient(timeout=15) as client:
        while True:
            r = await client.get(
                f"{API_URL}/subscriptions",
                params={"limit": 200, "offset": offset},
                headers=_headers(),
            )
            r.raise_for_status()
            subs = r.json()
            for s in subs:
                if _eligible(s, full_squads):
                    ids.add(int(s["user_id"]))
            if len(subs) < 200:
                break
            offset += 200
    return ids
