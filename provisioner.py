"""Создание канала OpenFlux под пользователя.

stub — имитация (без ноды, для локальной разработки).
real — провижн на ноде по SSH: provision-channel.sh + systemctl + чтение ссылки.
"""
from __future__ import annotations

import asyncio
import os
import re
import uuid

STUB = os.getenv("PROVISION_MODE", "stub") == "stub"

# --- конфиг ноды (из .env) ---
NODE = os.getenv("OPENFLUX_NODE", "root@45.151.183.236")          # user@host ноды
SSH_KEY = os.path.expanduser(os.getenv("SSH_KEY", "~/.ssh/openflux-bridge"))
SSH_PORT = os.getenv("SSH_PORT", "22")

# job_id -> {"status": "creating"|"ready"|"error", "link": str|None, "error": str|None}
_jobs: dict[str, dict] = {}


async def start(user_id: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"status": "creating", "link": None, "error": None, "user_id": user_id}
    asyncio.create_task(_run(job_id, user_id))
    return job_id


def get(job_id: str) -> dict | None:
    return _jobs.get(job_id)


async def _run(job_id: str, user_id: str) -> None:
    try:
        link = await (_provision_stub(user_id) if STUB else _provision_real(user_id))
        _jobs[job_id].update(status="ready", link=link)
    except Exception as error:  # noqa: BLE001 — текст ошибки уходит на страницу
        _jobs[job_id].update(status="error", error=str(error))


async def _provision_stub(user_id: str) -> str:
    await asyncio.sleep(5)
    return f"openflux://v1/DEMO-{user_id}-{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Выполнение команды на ноде по SSH и чтение её вывода.
# ---------------------------------------------------------------------------
async def run_on_node(command: str) -> str:
    """ssh на ноду, выполнить command, вернуть её stdout. Ошибка → исключение."""
    args = [
        "ssh",
        "-i", SSH_KEY,                               # ключ, которым логинимся
        "-p", SSH_PORT,
        "-o", "BatchMode=yes",                       # только ключ, никаких паролей-подсказок
        "-o", "StrictHostKeyChecking=accept-new",    # первый раз принять host key сам
        "-o", "ConnectTimeout=15",
        NODE, command,
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"нода {NODE}: {(err or out).decode().strip()}")
    return out.decode()


# ---------------------------------------------------------------------------
# Провижн канала: provision-channel.sh + systemctl + чтение ссылки.
# ---------------------------------------------------------------------------
async def _provision_real(user_id: str) -> str:
    # БЕЗОПАСНОСТЬ: user_id уходит в shell-команду на ноде. Пускаем только цифры,
    # иначе через хитрый user_id можно впихнуть свою команду на сервер.
    if not re.fullmatch(r"[0-9]{1,20}", str(user_id)):
        raise ValueError("user_id должен быть числом Telegram")
    channel = f"u{user_id}"

    # Уже есть канал у этого юзера? Вернуть его же ссылку (идемпотентность, reconnect).
    existing = await run_on_node(f"cat /root/channels/{channel}/link 2>/dev/null || true")
    if existing.strip():
        await run_on_node(f"systemctl start openflux-channel@{channel}")
        return existing.strip()

    # Новый канал: создать комнаты и сохранить (provision-channel.sh кладёт ссылку в .../link).
    await run_on_node(f"/root/provision-channel.sh {channel}")
    await run_on_node(f"systemctl start openflux-channel@{channel}")
    link = await run_on_node(f"cat /root/channels/{channel}/link")
    return link.strip()


# ---------------------------------------------------------------------------
# Для крона-сверки: список каналов на ноде и удаление одного.
# ---------------------------------------------------------------------------
async def list_channels() -> set[str]:
    """Имена каналов, что сейчас есть на ноде (папки /root/channels/u<id>)."""
    out = await run_on_node("ls /root/channels 2>/dev/null || true")
    return {line.strip() for line in out.splitlines() if line.strip()}


async def remove_channel(channel: str) -> None:
    """Погасить сервис канала и удалить его данные."""
    if not re.fullmatch(r"u[0-9]{1,20}", channel):   # только наши каналы вида u<цифры>
        raise ValueError(f"не наш канал: {channel}")
    await run_on_node(
        f"systemctl disable --now openflux-channel@{channel}; rm -rf /root/channels/{channel}"
    )
