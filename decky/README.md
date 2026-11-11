# DeckPilot Decky — v0.8.2 development

Install the reviewed app and plugin together. This development plugin expects backend schema 2; an older app shows an update message and the new profile controls stay disabled.

**Home → Find Games → Game Details → Settings** replaces the long one-page interface. Controls are large, wording is short, lists are paginated, and keyboard focus returns after saving. The main choices are still Best Graphics, Best Performance and Balanced.

Find installed/saved games or search all available Steam Store games by name/App ID. Results show IDs to distinguish similar titles. Game Details shows a short Checkup and recommendation. Sources open on a separate optional page. Saving a mode only records a preference. **Review & Apply → Apply Settings** is the explicit backup-first approval path. Cancel never edits files.

Settings selects Docked/Handheld manually. Changing the selection does not change game files; review and approve for that context. Advanced holds restore confirmation, optional existing FPS/frame-time logs, private diagnostic export/Drive controls and technical status. App updates and rollback require confirmation; the paired Stable/Preview update screen verifies the packages and prepares a local link for Decky’s supported Install from URL confirmation. No plugin installer runs silently. See [updates and first bootstrap](../docs/UPDATES.md).

Play-time recommendations are now a working **opt-in controlled Play button** (default Off). Enable in Advanced, then open an installed game and choose Play with DeckPilot. Cached advice precedes Apply & Play / Play Without Changes / Don’t Ask Again. The apply path shows all exact changes and requires approval before backup/apply/launch. Native Steam Play is **not** hooked or cancelled. See [the prototype guide](../docs/PLAY-PROTOTYPE.md). Actual launch behavior still needs Steam Deck testing.

The Python bridge still runs every app subprocess as the actual deck UID/GID/groups, with the deck home/runtime directory and user D-Bus session. Untrusted online text never reaches a shell or a local adapter.

## Build and test

```bash
npm ci
npm run typecheck
npm run build
npx playwright install --with-deps chromium
npm run test:ui
```

An existing Chromium can be selected with `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`. Browser tests use native-control Decky shims and mocked RPC; actual Steam controller navigation, virtual keyboard, Gaming Mode, native adapters, dock/TV and update/restart behavior require on-device tests. Generated bundles and test reports are ignored; lockfiles are committed.
