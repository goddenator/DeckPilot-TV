#!/usr/bin/env bash
set -euo pipefail
systemctl --user disable --now deckpilot-tv.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/deckpilot-tv.service" "$HOME/.local/bin/deckpilot-tv" "$HOME/.local/share/applications/deckpilot-tv.desktop" "$HOME/.local/share/applications/deckpilot-drive.desktop"
systemctl --user daemon-reload
printf 'Removed DeckPilot TV service and launcher.\n'
printf 'Saved backups and profiles have NOT been deleted: ~/.local/share/deckpilot-tv/\n'
printf 'To restore backed-up game configs first, run:\n'
printf '  python3 ~/.local/share/deckpilot-tv/app/deckpilot.py restore\n'
