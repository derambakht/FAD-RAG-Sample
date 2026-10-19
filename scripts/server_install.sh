#!/usr/bin/env bash
# نصب روی سرور لینوکس بدون Docker (مثلاً pod های RunPod که خودشان کانتینر هستند).
# از ریشه پروژه اجرا شود:   bash scripts/server_install.sh
# متغیرها: WITH_HF=1 (پیش‌فرض) برای embedding لوکال HuggingFace روی CPU، QDRANT_VERSION
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QDRANT_VERSION="${QDRANT_VERSION:-v1.19.2}"
WITH_HF="${WITH_HF:-1}"
BIN="$ROOT/bin"
cd "$ROOT"

echo "==> بسته‌های سیستم (Tesseract فارسی برای OCR)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends tesseract-ocr tesseract-ocr-fas curl ca-certificates >/dev/null

echo "==> uv و Python 3.12"
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
fi
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.12 >/dev/null
[ -d .venv ] || uv venv --python 3.12 .venv >/dev/null

echo "==> وابستگی‌های Python"
uv pip install --python .venv/bin/python -q -r requirements.txt
if [ "$WITH_HF" = "1" ]; then
  uv pip install --python .venv/bin/python -q torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
  uv pip install --python .venv/bin/python -q -r requirements-hf.txt
fi
.venv/bin/python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"

echo "==> Qdrant $QDRANT_VERSION"
mkdir -p "$BIN"
if [ ! -x "$BIN/qdrant" ] || ! "$BIN/qdrant" --version 2>/dev/null | grep -q "${QDRANT_VERSION#v}"; then
  curl -fsSL "https://github.com/qdrant/qdrant/releases/download/${QDRANT_VERSION}/qdrant-x86_64-unknown-linux-musl.tar.gz" \
    | tar -xz -C "$BIN" qdrant
fi
"$BIN/qdrant" --version

if [ ! -f .env ]; then
  cp .env.example .env
  sed -i "s/^VECTOR_STORE=.*/VECTOR_STORE=qdrant/; s|^# QDRANT_URL=.*|QDRANT_URL=http://127.0.0.1:6333|; s/^HOST=.*/HOST=127.0.0.1/" .env
  echo "فایل .env ساخته شد؛ OPENAI_API_KEY و APP_PASSWORD را تنظیم کنید."
fi
echo "==> نصب کامل شد. اجرا: bash scripts/server_start.sh"
