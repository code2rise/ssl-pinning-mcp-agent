#!/usr/bin/env bash
# start_server.sh — Launch the SSL Pinning MCP server
#
# Usage:
#   ./start_server.sh              # SSE transport (default) — for Continue.dev
#   ./start_server.sh http         # Streamable-HTTP — for Claude Code / Claude Desktop
#   ./start_server.sh sse          # SSE transport (explicit)
#   ./start_server.sh http 9000    # Streamable-HTTP on a custom port

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
SERVER="$SCRIPT_DIR/server.py"

# ── Resolve transport ─────────────────────────────────────────────────────────
ARG="${1:-sse}"
case "$ARG" in
  http|streamable-http)
    TRANSPORT="streamable-http"
    DEFAULT_PORT=8000
    ENDPOINT="/mcp"
    ;;
  sse|*)
    TRANSPORT="sse"
    DEFAULT_PORT=8000
    ENDPOINT="/sse"
    ;;
esac

PORT="${2:-$DEFAULT_PORT}"

# ── Sanity checks ─────────────────────────────────────────────────────────────
if [ ! -d "$VENV" ]; then
  echo "[error] Virtual environment not found at $VENV"
  echo "        Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# Check port is free
if lsof -iTCP:"$PORT" -sTCP:LISTEN &>/dev/null; then
  echo "[error] Port $PORT is already in use. Pass a different port: ./start_server.sh $ARG <port>"
  exit 1
fi

# ── Activate venv ─────────────────────────────────────────────────────────────
source "$VENV/bin/activate"

# ── Launch ────────────────────────────────────────────────────────────────────
echo ""
echo "  SSL Pinning MCP Server"
echo "  ──────────────────────────────────────────"
echo "  Transport : $TRANSPORT"
echo "  Endpoint  : http://localhost:$PORT$ENDPOINT"
echo "  Ctrl+C    : stop the server"
echo "  ──────────────────────────────────────────"
echo ""

MCP_TRANSPORT="$TRANSPORT" PORT="$PORT" python3 "$SERVER"
