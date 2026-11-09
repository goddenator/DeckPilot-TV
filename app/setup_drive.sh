#!/usr/bin/env bash
set -euo pipefail
printf '\nDeckPilot – Connect Google Drive\n\n'
DATA="$HOME/.local/share/deckpilot-tv"
mkdir -p "$DATA/bin"
if [[ -x "$DATA/bin/rclone" ]]; then
 RCLONE="$DATA/bin/rclone"
elif command -v rclone >/dev/null 2>&1; then
 RCLONE="$(command -v rclone)"
else
 echo 'Downloading rclone from its official site into your user folder (no sudo).'
 if ! command -v curl >/dev/null || ! command -v unzip >/dev/null; then
   echo 'curl and unzip are needed. No changes were made.'; read -rp 'Press Enter to close...' _; exit 1
 fi
 tmp="$(mktemp -d)"
 trap 'rm -rf "$tmp"' EXIT
 curl --fail --location --silent --show-error --retry 2 --max-time 180 'https://downloads.rclone.org/rclone-current-linux-amd64.zip' -o "$tmp/rclone.zip"
 # The official HTTPS download is the trust boundary for this optional helper.
 unzip -qq "$tmp/rclone.zip" -d "$tmp/unpacked"
 file="$(find "$tmp/unpacked" -type f -name rclone -print -quit)"
 if [[ -z "$file" ]] || [[ ! -f "$file" ]]; then echo 'rclone binary was not in downloaded archive'; exit 1; fi
 install -m 700 "$file" "$DATA/bin/rclone"
 RCLONE="$DATA/bin/rclone"
fi
if "$RCLONE" listremotes 2>/dev/null | grep -qx 'deckpilot:'; then
  echo 'Google Drive was already linked as deckpilot: .'
else
  echo 'Your browser should open for Google sign-in.'
  echo 'DeckPilot will request access to files it creates, not your entire Drive.'
  echo 'Do not copy the Google authorization token into ChatGPT.'
  echo 'If authorization fails, check the rclone Google Drive documentation.'
  # If Google retires rclone shared OAuth credentials, the user may need
  # their own free OAuth client ID; no paid API workaround is used here.
  "$RCLONE" config create deckpilot drive scope drive.file --no-output
fi
if "$RCLONE" listremotes | grep -qx 'deckpilot:'; then
 echo 'Connection configured! Open DeckPilot TV and enable Drive uploads if desired.'
else
 echo 'Connection was not completed. Nothing will be uploaded.'
fi
read -rp 'Press Enter to close this window...' _
