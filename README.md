# OpenFlux × Bedolaga bridge

Сервис, который при покупке тарифа в боте [Bedolaga](https://github.com/fr1ngg/remnawave-bedolaga-telegram-bot)
выдаёт пользователю дополнительный обход белых списков на базе
[OpenFlux](https://github.com/p1neappleXpress/OpenFlux): поздравление с кнопкой →
страница с автоподбором под ОС → автоматическое создание персонального канала
OpenFlux на ноде → `openflux://`-ссылка прямо в приложение.

Мост **самостоятельный**: не форк Bedolaga и не часть OpenFlux. С Bedolaga он
общается по её REST API и вебхукам, с нодами — по SSH. Код этих проектов внутри
не лежит.

---

## Как это работает

```
покупка тарифа Remnnawave
   │  Bedolaga → вебхук transaction.created
   ▼
[мост]  проверяет, что это нужная подписка (набор сквадов)
   │  Telegram Bot API → поздравление с inline-кнопкой
   ▼
пользователь жмёт кнопку → /connect?token=<подписанный>
   │  страница: детект ОС → приложение (Android apk / iOS TestFlight) → «Подключить»
   ▼
[мост]  SSH на ноду → provision-channel.sh → systemctl → openflux://
   ▼
ссылка открывается в приложении OpenFlux (на Android — в один тап)
```

Фоном крутится крон-сверка: удаляет каналы тех, у кого тариф больше не активен
(события истечения у Bedolaga нет — сверяем декларативно по `/subscriptions`).

---

## ⚠️ Важные тонкости (OpenFlux)

Здесь всё ломается по-тихому — читай внимательно.

### Транспорт cups.online + striped
- `cupsonline` 
  Данные идут из обновлени1 курсора/чисел. Аккаунт и каптча не нужны — поэтому удобно.
- Для нормальной скорости нужен **striped-транспорт**: несколько комнат =
  несколько параллельных полос + ARQ. Без него одна полоса ≈ 1.5–2 Мбит.
- Striped появился в ядре с **v0.7.1**, актуальная рабочая версия — **v0.13.0**.

### Версия ядра на ноде ДОЛЖНА совпадать с версией ядра в приложении
Если ядро на ноде и ядро в приложении разные — соединение молча
 уходит в **classic-режим** (одна полоса, медленно) или downlink вообще
мёртвый. Признак «работает, но медленно» — почти всегда это.
- Приложение **Android 3.7.0** = ядро `HEAD@4f9c786` = **core v0.13.0**.
- Значит бинарь `/root/openflux` на ноде собираем из **v0.13.0**.
- **Правило: ядро ноды = ядро приложения.** При обновлении приложения — обновляй ноды.

### Режим выхода l4
- Ноды работают в `--mode=l4` (gVisor): без root, на любом VPS.
- `l3` (raw, только Linux+root) быстрее, но требовательнее — для масштаба l4 проще.

### Ёмкость cups
- ~**100–116 комнат на один IP** (жёсткий потолок на ноду).
- По умолчанию **4 комнаты на канал** → ~28 каналов/нода. Меньше комнат = больше
  юзеров, но ниже пиковая скорость. Баланс мерить под свою нагрузку.
- Создание комнат rate-limited по IP (~7 за всплеск → `403`, отпускает за ~минуту).

---

## Предусловия

- Запущенный бот **Bedolaga** с включённым Web API (Bearer-токен) и вебхуками.
- Одна или несколько **нод-выходов** с установленным OpenFlux — см. [node/README.md](node/README.md).
- Домен + обратный прокси с TLS (пример на Caddy ниже).
- Docker + docker compose.

---

## Установка

### 1. Нода
Подними хотя бы одну ноду по инструкции [node/README.md](node/README.md)
(бинарь OpenFlux v0.13.0, `provision-channel.sh`, systemd-шаблон).

### 2. SSH-ключ мост → нода
```bash
ssh-keygen -t ed25519 -f ~/.ssh/openflux-bridge -N ""
ssh-copy-id -i ~/.ssh/openflux-bridge.pub root@<нода>
```

### 3. Конфиг
```bash
cp .env.example .env


### 4. APK (самохостинг)
```bash
./fetch-apk.sh        # скачает свежий universal apk в apk/openflux-android.apk
```

### 5. Запуск
```bash
docker compose up -d --build
```
Контейнер подключается к внешней docker-сети стека Bedolaga (имя сети задано в
`docker-compose.yml` ]]). Тогда мост видит бота как
`http://remnawave_bot:8080`, а прокси видит мост как `openflux_bridge:8099`.

### 6. Обратный прокси (пример Caddy)
```
orca.example.com {
    encode gzip zstd
    reverse_proxy openflux_bridge:8099
}
```
Caddy сам выпустит TLS-сертификат. Для nginx — обычный `proxy_pass` на тот же адрес.

### 7. Регистрация вебхука в Bedolaga
Один вебхук на событие `transaction.created`. Секрет придумываешь сам и кладёшь
в обе стороны (`.env` → `BEDOLAGA_WEBHOOK_SECRET` и в тело запроса):
```bash
curl -X POST http://localhost:8080/webhooks \
  -H "Authorization: Bearer $BEDOLAGA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"openflux-bridge","url":"https://orca.example.com/webhook","event_type":"transaction.created","secret":"<BEDOLAGA_WEBHOOK_SECRET>"}'
```

---

## Безопасность

- **Ссылка `/connect` подписана** (HMAC): `user_id` зашит в токен, подделать или
  перебрать нельзя. Токен выдаёт только сервер в момент покупки.
- **Вебхук проверяется** по HMAC-подписи Bedolaga — над *сырым* телом запроса
  (не над пере-сериализованным JSON, иначе подпись не сойдётся).
- **Провижн переспрашивает** `is_full_active`: даже с валидным токеном канал
  создаётся только при активной подписке FULL.

---

## Совместимость с Bedolaga

Проверено на Bedolaga **4.0.0** (репо `fr1ngg/remnawave-bedolaga-telegram-bot`):
- Покупка подписки = вебхук `transaction.created`, в payload `type=subscription_payment`
  (пополнение баланса — отдельное событие `payment.completed`).
- `/users/{X}` ищет по **telegram_id**, не по внутреннему id → маппинг через список.
- `/subscriptions` не отдаёт tariff_id → **FULL определяем по набору сквадов** (`FULL_SQUADS`).
- Ручки уведомления пользователя нет → поздравление шлём через Telegram Bot API.

---

## Структура

```
main.py              FastAPI: /webhook, /connect, /api/*, /download/android
provisioner.py       SSH на ноду: создание/удаление каналов
bedolaga.py          клиент REST API Bedolaga (подписки, telegram_id)
telegram.py          отправка сообщения + inline-кнопка
tokens.py            подписанные ссылки (HMAC)
reconcile.py         крон-сверка каналов с активными FULL
static/connect.html  страница подключения (детект ОС, звездопад)
fetch-apk.sh         скачать свежий Android apk для самохостинга
node/                скрипты для ноды-выхода (provision-channel.sh + systemd)
```

---

## Благодарности

- [OpenFlux](https://github.com/p1neappleXpress/OpenFlux) — транспорт обхода.
- [Bedolaga](https://github.com/fr1ngg/remnawave-bedolaga-telegram-bot) — Telegram-бот для Remnawave.

## Лицензия

[MIT](LICENSE)
