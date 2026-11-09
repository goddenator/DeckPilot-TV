#!/usr/bin/env bash
set -euo pipefail
python3 "$HOME/.local/share/deckpilot-tv/app/deckpilot.py" diagnose
printf '\n-- service state --\n'
systemctl --user is-active deckpilot-tv.service || true
printf '\n-- last 20 DeckPilot events --\n'
tail -n 20 "$HOME/.local/share/deckpilot-tv/deckpilot.log" 2>/dev/null || true
