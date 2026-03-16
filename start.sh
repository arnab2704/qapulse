#!/bin/bash
echo ""
echo "  ╔════════════════════════════════════╗"
echo "  ║   QA Pulse — Starting server...   ║"
echo "  ╚════════════════════════════════════╝"
echo ""

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "  ❌ Python 3 not found. Install from https://python.org"
    exit 1
fi

PY=$(python3 --version 2>&1)
echo "  ✓ $PY"
echo "  ✓ Starting on http://localhost:7337"
echo ""

# Open browser after 1 second
(sleep 1.2 && open http://localhost:7337 2>/dev/null || xdg-open http://localhost:7337 2>/dev/null) &

python3 "$(dirname "$0")/server.py"
