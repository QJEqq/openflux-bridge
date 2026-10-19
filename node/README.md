# Настройка ноды-выхода

Нода — это VPS, на котором мост по SSH создаёт каналы OpenFlux. На ноде нужен
собранный бинарь OpenFlux, скрипт провижена и systemd-шаблон.

## 1. Бинарь OpenFlux

> ⚠️ **Версия ядра на ноде ДОЛЖНА совпадать с версией ядра в приложении.**
> Иначе соединение молча падает в медленный classic-режим или рвётся.
> Для приложения Android 3.7.0 (ядро `HEAD@4f9c786`) собирай ядро **v0.13.0**.
> См. раздел «Важные тонкости» в корневом README.

Собери OpenFlux нужного тега и положи бинарь в `/root/openflux`:

```bash
git clone https://github.com/p1neappleXpress/OpenFlux
cd OpenFlux && git checkout v0.13.0
# собери по инструкции репозитория, затем:
install -m 0755 <собранный-бинарь> /root/openflux
```

На ноде нужен `python3` — скрипт провижена достаёт список комнат из ссылки.

## 2. Скрипт и systemd-шаблон

```bash
install -m 0755 provision-channel.sh /root/provision-channel.sh
install -m 0644 openflux-channel@.service /etc/systemd/system/openflux-channel@.service
systemctl daemon-reload
```

## 3. Проверка

```bash
/root/provision-channel.sh u999          # создаст комнаты, вернёт openflux://...
systemctl start openflux-channel@u999    # поднимет канал
systemctl status openflux-channel@u999
# удалить тест:
systemctl disable --now openflux-channel@u999 && rm -rf /root/channels/u999
```

## Как это работает

- `provision-channel.sh` запускает OpenFlux в режиме `--share` (`--mode=l4` —
  gVisor, без root), ловит из лога `openflux://`-ссылку, достаёт из неё список
  cups-комнат и сохраняет в `/root/channels/<id>/{env,link}`.
- `openflux-channel@<id>.service` держит канал поднятым (`--url=${ROOMS}` из env),
  перезапускает при падении.
- Мост зовёт именно эти пути/имена — менять их на ноде нельзя (это контракт
  с `provisioner.py`).

## Ёмкость

- cups держит **~100–116 комнат на один IP** (жёсткий потолок на ноду).
- `CreateRoomList` по умолчанию создаёт **4 комнаты на канал** → ~28 каналов/нода.
- Меньше комнат на канал = больше юзеров, но ниже пиковая скорость (комнаты =
  параллельные полосы striped-транспорта). Баланс мерить под свою нагрузку.
- Создание комнат rate-limited по IP (~7 за всплеск → `403`, отпускает за ~минуту).
