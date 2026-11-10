# DeckPilot TV Decky plugin v0.8.0

Install the separately built plugin through Decky Loader after the DeckPilot user service is installed. Routine use is in Gaming Mode: three default modes, Steam-wide name/App ID search, installed/saved game selection, per-game modes, independent community reports, preview/approval, restore, display diagnostics, and approved app update/rollback controls.

Search results show App IDs to distinguish similar titles. Research verifies the selected identity with Steam before querying Deck Settings / deckverified.games, ShareDeck and SteamDeckHQ. Saving a mode for an uninstalled game persists the App ID preference; preview compatible settings after installation/first launch. Unknown games stay advisory. Source failures do not prevent offline preferences or safe local adapters from working.

The Python bridge resolves the actual `deck` account and drops root's UID/GID/supplementary groups for **every** app subprocess. It sets the deck user's home, XDG runtime/config/data directories and D-Bus session for user-space updates. It fails closed on an account/home mismatch. It never invokes shell commands from online reports.

Build from this directory with Node 22+:

```bash
npm ci
npm run typecheck
npm run build
```

The root packaging helper includes `dist/index.js` in the plugin ZIP. Generated bundles/node_modules are ignored; the lockfile is committed. Actual controller behavior, external link navigation and SteamOS identity/session handling still require on-device validation. See [source and adapter limits](../docs/RESEARCH.md).
