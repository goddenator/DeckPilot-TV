#!/usr/bin/env bash
set -euo pipefail
APPDIR="$HOME/.local/share/deckpilot-tv/app"
BINDIR="$HOME/.local/bin"
UNITDIR="$HOME/.config/systemd/user"
DESKTOPDIR="$HOME/.local/share/applications"
TOOLSDIR="$HOME/.local/share/deckpilot-tv/tools"
mkdir -p "$APPDIR" "$BINDIR" "$UNITDIR" "$DESKTOPDIR" "$TOOLSDIR"
# On the first upgrade from v0.3, save old app files before replacing anything.
PREVIOUS="$HOME/.local/share/deckpilot-tv/updates/previous-app"
if [[ -f "$APPDIR/deckpilot.py" && ! -f "$PREVIOUS/deckpilot.py" ]]; then
  mkdir -p "$PREVIOUS"
  for name in deckpilot.py updater.py VERSION.txt; do
    [[ ! -f "$APPDIR/$name" ]] || cp "$APPDIR/$name" "$PREVIOUS/$name"
  done
fi
cp "$(dirname "$(readlink -f "$0")")/deckpilot.py" "$APPDIR/deckpilot.py"
cp "$(dirname "$(readlink -f "$0")")/updater.py" "$APPDIR/updater.py"
cp "$(dirname "$(readlink -f "$0")")/VERSION.txt" "$APPDIR/VERSION.txt"
cp "$(dirname "$(readlink -f "$0")")/setup_drive.sh" "$TOOLSDIR/setup_drive.sh"
chmod 700 "$APPDIR/deckpilot.py" "$APPDIR/updater.py" "$TOOLSDIR/setup_drive.sh"
cat > "$UNITDIR/deckpilot-tv.service" <<EOF
[Unit]
Description=DeckPilot TV local game profile synchronizer
After=default.target
[Service]
Type=simple
ExecStart=/usr/bin/python3 %h/.local/share/deckpilot-tv/app/deckpilot.py serve
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
[Install]
WantedBy=default.target
EOF
cat > "$BINDIR/deckpilot-tv" <<'EOF'
#!/usr/bin/env bash
systemctl --user start deckpilot-tv.service
for i in {1..30}; do
 if /usr/bin/python3 -c 'import urllib.request;urllib.request.urlopen("http://127.0.0.1:38647/",timeout=1)' >/dev/null 2>&1; then break; fi
 sleep .3
done
xdg-open http://127.0.0.1:38647/
EOF
chmod 700 "$BINDIR/deckpilot-tv"
cat > "$DESKTOPDIR/deckpilot-tv.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DeckPilot TV
Comment=Choose automatic graphics, performance or balanced settings
Exec=$BINDIR/deckpilot-tv
Terminal=false
Categories=Game;Utility;
Icon=applications-games
EOF
cat > "$DESKTOPDIR/deckpilot-drive.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DeckPilot - Connect Drive
Comment=One-time Google Drive link for one tidy diagnostics file
Exec=konsole -e bash $TOOLSDIR/setup_drive.sh
Terminal=false
Categories=Game;Utility;
Icon=folder-cloud
EOF
systemctl --user daemon-reload
systemctl --user enable deckpilot-tv.service
systemctl --user restart deckpilot-tv.service
printf '\nDeckPilot TV installed.\nOpen "DeckPilot TV" in Desktop Mode application launcher.\nSettings and backups: %s\n' "$HOME/.local/share/deckpilot-tv"
