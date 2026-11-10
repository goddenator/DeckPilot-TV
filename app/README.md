# DeckPilot TV v0.8.2

Experimental Steam Deck OLED/docked-TV research and cautious settings tool. No paid API or subscription. Community evidence does not guarantee TV performance; the official Valve dock supports up to 4K60 or 1440p120 depending on connection, not guaranteed 4K120.

Unreleased development build. See [the roadmap](../docs/ROADMAP.md) for larger features and hardware acceptance.

## Routine use

Use **Home / Find Games / Game Details / Settings** in the Decky panel in Gaming Mode to search Steam by title or App ID, including uninstalled games. Check the exact name/App ID before selecting. Research queries Deck Settings / deckverified.games, ShareDeck and SteamDeckHQ independently, with links/dates and unknown fields labelled. OLED/docked reports rank first when available. Handheld-only reports are labelled; reported averages and FPS caps/targets are distinct.

Choose **Best Graphics**, **Best Performance** or **Balanced** globally or per game. Per-game choices survive global default changes and can be saved before installation. Select separate **Docked** and **Handheld** profiles in Settings; selection is manual and never edits files. Legacy choices populate both profiles initially. A private recovery copy retains inactive choices across an older app rewriting legacy fields after rollback. Local editing requires an installed compatible config, a closed game, **Review & Apply**, then **Apply Settings**. When a game is not installed or supported, its preference stays saved and reports are advisory. Launch a newly installed game once so it can create its config, then preview and approve. After approval, the service can synchronize that same mode without overwriting newer user/game edits.

Existing compatible Unreal Engine configs use provisional 1080p/high, 900p/medium or 720p/low starting points. Native Valheim and Hollow Knight support is limited to existing XML resolution preferences; quality remains advisory. No online text becomes commands/settings, and no Steam launch options, display modes, TDP, Gamescope controls or saves are modified. See [detailed limits](../docs/RESEARCH.md).

Game Checkup verifies matching local settings, manual changes and safe restore availability. Restore is available per game under Advanced in Decky or through the Desktop dashboard. It restores only unchanged managed files, preserves manual edits, keeps backups, and stops future reapplication until approved again. A new preview is needed if config contents change. Upgrading from an older app keeps preferences/backups but requires explicit approval for local settings changes.

## Installation and updates

For a reviewed/published release, extract `DeckPilot_TV_v0.8.2.zip` in Desktop Mode and run its `install.sh` once. The installer runs as your user and keeps existing preferences/backups. This development branch does not publish a release or provide an on-device verified binary.

After initial setup, use the existing trusted GitHub release feed for automatic checks/downloads and the Decky Settings update/rollback confirmation controls. Decky plugin updates remain a separate manual approval; they are never silently installed. The Desktop dashboard can connect/disconnect a trusted `owner/repo` feed. Installation requires explicit approval, a GitHub-issued SHA256 digest, a frozen archive with a digest rechecked at installation, strict ZIP/manifest validation and a successful restart check; rollback remains available. A missing release, blocked API or rate limit is reported separately. No routine manual Konsole commands are required after installation.

## Private diagnostics

The Desktop dashboard's **Diagnostics and private Google Drive** section can export a local ZIP for review. Uploads are **off by default**. Connect Drive once through **DeckPilot - Connect Drive**, review an export, then enable uploads only if wanted. OAuth credentials remain with rclone; its `drive.file` scope limits access to files it creates. Google/rclone OAuth configuration may require a separate free OAuth client if shared credentials no longer work.

Uploads overwrite only `My Drive / DeckPilot Diagnostics / DeckPilot-Latest.zip`. DeckPilot never creates public sharing links. Reports omit raw game configs and manifests and redact sensitive log data, but redaction is best-effort; review before sharing. Display diagnostics distinguish supported adapters and unsupported games, advertised modes/VRR capability, and unknown active mode/VRR enabled status.

## Development validation

From the repository root:

```bash
python3 -m unittest discover -s app -v
bash -n app/install.sh app/setup_drive.sh app/uninstall.sh app/check.sh
```

Tests mock third-party services. Live source access, Drive OAuth/upload, SteamOS user services and Deck/dock/TV performance still need device validation. Saved preferences and backups are retained on uninstall.


## Optional measurements and offline evidence

Existing FPS logs are off by default. Advanced can enable read-only summaries of attributable MangoHud CSV samples: average FPS and actual frame-time average/p95 in milliseconds. No recording starts, raw CSV uploads, or automatic tuning takes place. The profile/session of existing logs is unverified. Similarly named games and generic mangoapp logs are excluded.

Community report confidence describes specificity/recency of independent evidence for the selected display context, not guaranteed FPS. Retained verified identity/reports can be used offline for up to 30 days and are labelled cached/stale; stale evidence lowers confidence. No initial cache means an offline lookup fails clearly.

Steam’s own Play remains untouched. A working opt-in **DeckPilot Play button** now implements cached advice, exact approval/backup/apply and an ordinary Steam launch request. See [the prototype guide](../docs/PLAY-PROTOTYPE.md). Native interception is not implemented.
