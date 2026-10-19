"""Крон-сверка: каналы на ноде должны соответствовать активным FULL-подпискам.

Декларативный подход («каналы = активные FULL-юзеры»), а не ловля события
истечения (его у Bedolaga и нет). Сам чинит отвал подписки, отмену, возврат.

RECONCILE_MODE:
  off    — ничего не делать (по умолчанию, безопасно)
  dryrun — только печатать, что удалил бы (прогони сначала так!)
  on     — реально удалять каналы юзеров без активной FULL-подписки
"""
from __future__ import annotations

import asyncio
import os

import bedolaga
import provisioner

MODE = os.getenv("RECONCILE_MODE", "off")
INTERVAL = int(os.getenv("RECONCILE_INTERVAL", "600"))   # секунд между проверками
FULL_SQUADS = {s.strip() for s in os.getenv("FULL_SQUADS", "").split(",") if s.strip()}


async def reconcile_once() -> None:
    if MODE == "off":
        return
    active = await bedolaga.active_full_user_ids(FULL_SQUADS)
    existing = {ch for ch in await provisioner.list_channels() if ch.startswith("u")}

    # Предохранитель: «ни одной активной FULL, но каналы есть» — почти всегда сбой
    # API/конфига, а не массовое истечение. Не выпиливаем всё разом.
    if not active and existing:
        print("[reconcile] активных FULL нет, а каналы есть — пропускаю (похоже на сбой)", flush=True)
        return

    desired = {f"u{uid}" for uid in active}
    for ch in existing - desired:
        if MODE == "dryrun":
            print(f"[reconcile] DRYRUN: удалил бы {ch}", flush=True)
            continue
        await provisioner.remove_channel(ch)
        print(f"[reconcile] удалён канал без активной FULL: {ch}", flush=True)


async def loop() -> None:
    while True:
        try:
            await reconcile_once()
        except Exception as error:   # noqa: BLE001 — крон не должен падать, иначе вообще не удалит
            print(f"[reconcile] ошибка: {error}", flush=True)
        await asyncio.sleep(INTERVAL)
