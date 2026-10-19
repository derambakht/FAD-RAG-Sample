#!/usr/bin/env bash
# اجرای Qdrant و برنامه در پس‌زمینه (بدون systemd). اجرای مجدد، فرایندها را ری‌استارت می‌کند.
#   bash scripts/server_start.sh          شروع/ری‌استارت
#   bash scripts/server_start.sh stop     توقف
# لاگ‌ها: logs/qdrant.log و logs/app.log
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs data/qdrant-storage
APP_PORT="${APP_PORT:-$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 || true)}"
APP_PORT="${APP_PORT:-8000}"
APP_HOST="${APP_HOST:-$(grep -E '^HOST=' .env 2>/dev/null | cut -d= -f2 || true)}"
APP_HOST="${APP_HOST:-127.0.0.1}"

stop() {
  for name in app qdrant; do
    if [ -f "logs/$name.pid" ] && kill -0 "$(cat logs/$name.pid)" 2>/dev/null; then
      kill "$(cat logs/$name.pid)" && echo "توقف $name"
      for _ in $(seq 1 20); do kill -0 "$(cat logs/$name.pid)" 2>/dev/null || break; sleep 0.5; done
    fi
    rm -f "logs/$name.pid"
  done
}

stop
[ "${1:-}" = "stop" ] && exit 0

# Qdrant فقط روی localhost؛ از بیرون فقط از طریق برنامه در دسترس است
QDRANT__SERVICE__HOST=127.0.0.1 QDRANT__SERVICE__HTTP_PORT=6333 QDRANT__SERVICE__GRPC_PORT=6334 \
QDRANT__STORAGE__STORAGE_PATH="$ROOT/data/qdrant-storage" QDRANT__TELEMETRY_DISABLED=true \
  nohup bin/qdrant >> logs/qdrant.log 2>&1 &
echo $! > logs/qdrant.pid
for _ in $(seq 1 40); do curl -fs http://127.0.0.1:6333/readyz >/dev/null && break; sleep 0.5; done
curl -fs http://127.0.0.1:6333/readyz >/dev/null && echo "Qdrant آماده است" || { echo "Qdrant بالا نیامد؛ logs/qdrant.log را ببینید"; exit 1; }

# یک worker؛ کارهای پس‌زمینه و کش BM25 درون فرایند هستند
HF_HOME="$ROOT/data/hf-cache" nohup .venv/bin/python -m uvicorn app.main:app --host "$APP_HOST" --port "$APP_PORT" \
  --proxy-headers --forwarded-allow-ips='*' >> logs/app.log 2>&1 &
echo $! > logs/app.pid
for _ in $(seq 1 60); do curl -fs "http://127.0.0.1:$APP_PORT/api/health" >/dev/null && break; sleep 0.5; done
curl -fs "http://127.0.0.1:$APP_PORT/api/health" && echo && echo "برنامه روی پورت $APP_PORT آماده است" \
  || { echo "برنامه بالا نیامد؛ logs/app.log را ببینید"; exit 1; }
