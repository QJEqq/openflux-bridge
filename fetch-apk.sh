#!/usr/bin/env bash
# Скачивает свежий universal-APK OpenFluxAndroid в ./apk/openflux-android.apk,
# откуда мост отдаёт его на /download/android (самохостинг, один тап для юзера).
# Перезапускать при выходе новой версии приложения. apk в git НЕ коммитим.
set -euo pipefail

REPO="${OPENFLUX_ANDROID_REPO:-p1neappleXpress/OpenFluxAndroid}"
DEST_DIR="$(cd "$(dirname "$0")" && pwd)/apk"
mkdir -p "$DEST_DIR"

echo "Ищу последний релиз $REPO…"
URL=$(curl -sSL "https://api.github.com/repos/$REPO/releases/latest" \
  | grep -oE '"browser_download_url": *"[^"]*universal-release\.apk"' \
  | head -1 | sed -E 's/.*"(https[^"]+)".*/\1/')

if [ -z "${URL:-}" ]; then
  echo "Не нашёл universal-apk в последнем релизе — проверь репозиторий." >&2
  exit 1
fi

echo "Качаю: $URL"
curl -sSL -o "$DEST_DIR/openflux-android.apk" "$URL"
echo "Готово: $DEST_DIR/openflux-android.apk ($(du -h "$DEST_DIR/openflux-android.apk" | cut -f1))"
