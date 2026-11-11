# DeckPilot TV — v0.8.3-preview.5 development

Stage 1: [Gaming Mode updates, limitations and device checklist](docs/PREVIEW-5.md). [Full implementation programme](docs/IMPLEMENTATION-PLAN.md). Published preview.4 remains unchanged.

A free, cautious Steam Deck OLED optimisation assistant with three choices: **Best Graphics**, **Best Performance**, and **Balanced**. This is an unreleased development build on PR #3; nothing is merged or published.

The Decky interface has four simple screens:

- **Home** — choose how you want to play.
- **Find Games** — your library or Steam-wide search, including uninstalled games.
- **Game Details** — Game Checkup, three choices, review/approve local changes, and short community advice. Sources are optional.
- **Settings** — select a separate Docked/Handheld profile and review updates. Restore, measurements and private diagnostics live under **Advanced**.

Profiles are selected manually. Switching profiles never edits files. A concrete preview and approval are required before a compatible local adapter can apply settings, with backups first and newer user changes protected. Native Valheim and Hollow Knight support is limited to existing XML resolution settings; other unknown formats remain advisory. Saves and Steam launch options are untouched.

Independent Deck Settings / deckverified.games, ShareDeck and SteamDeckHQ reports retain provenance, evidence confidence, and offline cache labels. Balanced is a conservative starting recommendation, not a promise of optimal or achieved performance. Optional analysis reads existing attributable FPS/frame-time logs only; it does not start a recorder or automatically learn/apply settings.

**Play-time prototype:** enable it in Advanced, then use **Play with DeckPilot** on an installed game's Details screen. It offers cached advice, Apply & Play with exact preview/approval and backups, Play Without Changes, and per-game Don’t Ask Again. Steam’s **own** Play button is not intercepted. See [prototype usage, failures and device checklist](docs/PLAY-PROTOTYPE.md). The tested four-screen layout is preserved; no release is published.

**Stable / Preview updates:** Settings → Updates provides Update Everything, app-first restart verification and a verified ZIP prepared for Decky’s Gaming Mode file picker. Loader still asks before installing; exact installed-file verification is required before Done. The new path needs Steam Deck validation. See [update usage, publication approval and recovery](docs/UPDATES.md).

See [app usage](app/README.md), [Decky usage](decky/README.md), and [research provenance](docs/RESEARCH.md).

See the [Preview.3 reliability audit, fixed defects, residual risks and controller-only device checklist](docs/RELIABILITY-AUDIT.md).

## Development checks

Use the existing checkout; no worktree is needed. Python 3.10+ and Node 22+:

```bash
node --test .github/scripts/publication-guard.test.cjs
python3 -m unittest discover -s app -v
bash -n app/install.sh app/setup_drive.sh app/uninstall.sh app/check.sh
cd decky
npm ci
npm run typecheck
npm run build
npx playwright install --with-deps chromium
npm run test:ui
cd ..
python3 tools/package_release.py
```

UI tests render the production React app with Decky RPC/component shims in Chromium. They exercise navigation, keyboard focus, approval, errors, profiles and opt-ins; they do not validate Steam's actual controller focus engine. For an already installed Chromium, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium` for `npm run test:ui`.

Optional Desktop dashboard smoke test: `python3 tools/smoke_dashboard.py` (Python Playwright/Chromium required). It uses temporary data and an ephemeral port.

Packaging creates local app/plugin ZIPs in `out/` and never publishes. The old updater's app-file allowlist is retained. App installation requires approval and strict validation; online packages are rechecked against the approved GitHub digest. Plugin updates are never silently installed. CI runs Python, TypeScript, build and Decky browser tests for development branches/PRs; publishing remains a separate approved tag/release action.
