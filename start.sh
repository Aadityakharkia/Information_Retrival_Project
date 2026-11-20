#!/usr/bin/env bash
# One-command launcher for macOS / Linux:  ./start.sh
# Creates a virtual environment outside this (possibly iCloud-synced) folder, installs
# dependencies the first time, starts the server and opens the browser.
set -e
cd "$(dirname "$0")"
VENV="${SEARCHBRIDGE_VENV:-$HOME/.venvs/searchbridge}"
PY="${PYTHON:-python3}"
if [ ! -x "$VENV/bin/python" ]; then
  echo "Creating virtual environment in $VENV"
  "$PY" -m venv "$VENV"
fi
source "$VENV/bin/activate"
if ! python -c "import fastapi, sklearn, scipy, multipart" 2>/dev/null; then
  echo "Installing dependencies (first run only)…"
  pip install -q --upgrade pip
  pip install -q -r requirements.txt
fi
# Better semantic search: Sentence-BERT (installs PyTorch, a few hundred MB, first run only).
# Skip with SEARCHBRIDGE_LITE=1; the app falls back to LSA if this is unavailable.
if [ -z "$SEARCHBRIDGE_LITE" ] && ! python -c "import sentence_transformers" 2>/dev/null; then
  echo "Installing sentence-transformers for semantic search (first run only, a few minutes)…"
  pip install -q sentence-transformers || echo "  (skipped: semantic search will use LSA instead)"
fi
# Research Papers 2016-2025 (OpenAlex, real citation links). OpenAlex answered 401 without an API key during
# development, so the download only runs when OPENALEX_API_KEY is set: export OPENALEX_API_KEY=... && ./start.sh
if [ ! -f data/research_papers/papers.jsonl.gz ]; then
  if [ -n "$OPENALEX_API_KEY" ]; then
    echo "Downloading the Research Papers 2016-2025 collection from OpenAlex…"
    python scripts/fetch_openalex.py || echo "  (download failed: the other collections are still available)"
  else
    echo "Research Papers collection not downloaded (set OPENALEX_API_KEY to fetch it). Classic CS, Cranfield and your Library are available."
  fi
fi
PORT="${PORT:-8000}"
URL="http://127.0.0.1:$PORT"
echo "SearchBridge is starting at $URL (first start indexes the collections, 1-3 minutes; later starts are instant)"
( sleep 2; (command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") || true ) &
exec python -m uvicorn app.server:app --host 127.0.0.1 --port "$PORT"
