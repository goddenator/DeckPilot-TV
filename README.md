# DeckPilot TV v0.8.0

A cautious, free Steam Deck settings research tool with exactly three modes: **Best Graphics**, **Best Performance**, and **Balanced**. Select defaults and per-game preferences in Gaming Mode through Decky, including games that are not installed.

Steam-wide name/App ID search uses the public Steam Store. Research verifies the selected App ID and independently queries Deck Settings / deckverified.games, ShareDeck, and SteamDeckHQ. Reports retain their source, date, device and available settings metadata. Unknown metadata stays unknown; handheld evidence and FPS targets are labelled. Community reports are advisory and never become executable commands or configuration instructions.

Local application supports existing compatible Unreal Engine configs and a limited native Linux Valheim resolution adapter. **Preview → approve → back up → apply** is required. Running games, unknown formats, symlinks, and later manual edits are skipped. Restore keeps newer user edits and stops automatic reapplication. No universal game adapter, TV performance guarantee, or hardware benchmark is claimed.

See [app usage](app/README.md), [Decky usage](decky/README.md), and [source contracts, provenance and limits](docs/RESEARCH.md).

## Development

Python 3.10+ and Node 22+ are required. Use the existing checkout; no worktree is needed.

```bash
python3 -m unittest discover -s app -v
bash -n app/install.sh app/setup_drive.sh app/uninstall.sh app/check.sh
cd decky
npm ci
npm run typecheck
npm run build
cd ..
python3 tools/package_release.py
```

Packaging creates local v0.8.0 app and Decky ZIPs under `out/`; it never publishes. The app package deliberately retains the old updater's file allowlist so a trusted, approved update from v0.6 can install the new runtime. SHA256 checks, strict archive validation, explicit installation approval and rollback are retained. CI tests/builds development branches and PRs; only a separately pushed matching version tag can publish a release.

Live source access was blocked by this cloud environment's outbound proxy. Public API schemas were inspected in upstream source and exercised with synthetic fixtures, but live source responses and actual Steam Deck OLED/dock/TV behavior still need validation. No release has been published by this change.

Optional Desktop browser smoke test (Python Playwright and Chromium installed): `python3 tools/smoke_dashboard.py`. It uses temporary data and an ephemeral port, without touching an installed service.
