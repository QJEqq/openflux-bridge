#!/usr/bin/env bash
# Создаёт персональный канал OpenFlux (cups-комнаты) под id.
# Запускает openflux в режиме share, ловит из лога openflux://-ссылку,
# достаёт из неё список комнат и сохраняет в /root/channels/<id>/{env,link}.
# Дальше канал держит systemd-юнит openflux-channel@<id>.
#
# Использование:  ./provision-channel.sh <id> [--force]
set -u
id="${1:?укажи id канала}"; force="${2:-}"; dir="/root/channels/$id"; BIN=/root/openflux
mkdir -p "$dir"
if [ -f "$dir/env" ] && [ "$force" != "--force" ]; then
  echo "канал $id уже провиженен; для пересоздания: $0 $id --force"; exit 1
fi
echo "создаю комнаты для $id (до ~150 c)..."
timeout 150 "$BIN" --role=exit --mode=l4 --transport=cupsonline --share --debug > "$dir/provision.log" 2>&1 &
pid=$!; link=""
for t in $(seq 1 45); do link=$(grep -ao 'openflux://[A-Za-z0-9/_+=.-]*' "$dir/provision.log" | head -1); [ -n "$link" ] && break; sleep 3; done
kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
[ -z "$link" ] && { echo "НЕ создались комнаты — $dir/provision.log (возможно cups 403)"; exit 1; }
rooms=$("$BIN" --parse-link "$link" | python3 -I -c 'import sys,json; print(json.load(sys.stdin)["config"]["transports"][0]["url"])')
[ -z "$rooms" ] || [ "$rooms" = "None" ] && { echo "не достал комнаты из ссылки"; exit 1; }
echo "ROOMS=$rooms" > "$dir/env"; echo "$link" > "$dir/link"
echo "канал $id готов: $link"
