#!/usr/bin/env bash
# throughline one-shot installer. Wires the injector hook into Codex and/or Claude Code.
# Usage: ./install.sh [--codex] [--claude] [--print] [--uninstall]
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/skills/throughline/scripts/install.py" "$@"
