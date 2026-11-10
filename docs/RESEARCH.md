# Research contracts and review notes

DeckPilot has no paid AI service, API key, subscription, or background web search. Research happens on demand and is advisory. It is independent of local adapter constants.

## Public interfaces and provenance

| Source | Public interface | Identity and metadata |
| --- | --- | --- |
| Steam | `store.steampowered.com/api/storesearch/?term=...&l=english&cc=GB`, then `/api/appdetails?appids=...&l=english` | Show name and App ID together; verify `success`, `steam_appid` and game type before research. Name search results alone are not identity verification. |
| Deck Settings / deckverified.games | `/deck-verified/api/v1/game_details?appid=...&include_external=false` | Check both `appId` and each `reports[].data.app_id`. Keep only this publisher's community reports; do not blend `external_reviews`. Preserve original report links, dates, device, resolution and target framerate. |
| ShareDeck | `sharedeck.games/api/experimental/reports?app_id=...` | Check each `app_id`; preserve report ID, creation date, `app_build_id`, resolution and reported average framerate. Never equate `framerate_limit` with measured FPS. Device/display context often are unavailable. |
| SteamDeckHQ | `/wp-json/wp/v2/game-reviews/?meta_key=steam_app_id&meta_value=...&per_page=5` | Do not trust query filtering alone: require an explicit matching record ID or a unique Steam store link in the review. Preserve review URL/date; configured FPS caps are targets, not observed FPS. Never assume LCD or OLED when not stated. |

Schema evidence inspected on 2026-11-10:

- [DeckSettings/deck-verified-site](https://github.com/DeckSettings/deck-verified-site/tree/34c0708ca01b7041558b6485324962a308d1dcde): `packages/frontend/src/utils/api.ts`, `packages/shared/src/game.ts`, and `packages/backend/src/external/sdhq.ts`.
- [davocarli/sharedeck-y](https://github.com/davocarli/sharedeck-y/tree/28a30fba3d1f3a18d181c90810cb8a1a0c2b9ba5): `src/constants.ts` and `src/context/index.tsx`.

These are interface/schema references; upstream implementation code is not vendored. Synthetic fixtures in `app/test_research.py` exercise those contracts. A schema reference does not establish current live service availability.

## Fetching and safety

Each publisher has an independent result/status. DeckPilot honors robots.txt for community sites and fails closed if access policy cannot be obtained (a genuine 404 means no robots restrictions). It does not bypass challenges, authentication or blocked access. Fixed HTTPS destinations, same-publisher redirects, TLS verification, a 1 MiB response limit, short socket timeouts and an eight-second per-source budget bound requests. The aggregate waits at most ten seconds after Steam verification. Successful results are cached for six hours; unavailable sources for five minutes. Robots rules are cached for one hour. One private cache retains at most 64 entries. No credentials or arbitrary source URLs are accepted from the UI.

Only exact App ID evidence is accepted; ambiguous/unsupported formats yield no verified reports. Missing dates, devices, game versions, resolutions and FPS remain unknown. OLED and docked evidence ranks first where explicitly identified. Mixed or absent display context stays unknown. Original descriptions remain untrusted text, rendered as text or escaped HTML. Downloaded commands, launch options and settings instructions are never executed or passed to local adapters.

## Local settings

- The compatible Unreal Engine adapter edits only known keys in existing `Saved/Config/{Windows,WindowsNoEditor,WinGDK}/GameUserSettings.ini` files in the game's Proton prefix. These are provisional resolution/scalability starting points, not source-derived or benchmarked settings.
- Native Linux Valheim (Steam App ID 892970) supports only existing Unity XML `Screenmanager Resolution Width` and `Screenmanager Resolution Height` integer entries under `~/.config/unity3d/IronGate/Valheim/prefs`. No quality keys are guessed; saves, Proton registry, binary/unknown preferences and XML declarations are untouched. This adapter still needs SteamOS hardware validation.
- Preset selection saves preferences only. Uninstalled games retain choices by App ID; after installation and first launch, preview and approve compatible local changes. Unsupported games stay advisory.
- Preview fingerprints bind approval to the exact local file contents and mode. Back up before replacement, preserve original snapshots across cycles, reject stale previews, skip running games/manual edits, and serialize CLI/service transactions with a file lock. Restore refuses newer manual edits and disables reapplication for that game.
- Changing the global default preserves per-game overrides. An older install's enabled flag does not implicitly approve new edits. Explicit preview/approval is required after this upgrade.

## Diagnostics, updates and limitations

Display diagnostics report connected external DRM connectors, advertised resolution modes and VRR capability independently from active mode/refresh and VRR enabled state. Unknown is never labelled disabled or enabled. No Gamescope, display, TDP, launch-option or Steam client changes are made. An official Valve dock is not a guarantee of 4K120; its published limits are up to 4K60 or 1440p120 depending on connection.

Diagnostics remain opt-in, redacted, and exclude raw configs/manifests. The private rclone Drive destination remains exactly `deckpilot:DeckPilot Diagnostics/DeckPilot-Latest.zip`, overwritten in place. There are no public sharing/link commands. Redaction is best-effort: export and review before enabling. OAuth remains with rclone, never in research requests.

Existing trusted GitHub feeds keep automatic checks and verified downloads; installation/rollback remain approved actions. Update errors distinguish absent public releases, denied/rate-limited access, verification failures and connectivity problems without leaking remote error bodies. Decky launches Python with the deck account's UID/GID/groups, home, runtime directory and user D-Bus session even when its backend is root; it fails closed if that account cannot be resolved.

This environment denied outbound connections to Steam and the research sites with HTTP 403 CONNECT errors. Allow `store.steampowered.com`, `deckverified.games`, `sharedeck.games`, `www.sharedeck.games`, and `steamdeckhq.com` for live validation. `api.github.com` is also required for release checks/PR creation. Public Store search can omit region-restricted, delisted or non-game entries; it is not an offline complete Steam catalog. Experimental/public schemas may change and cause graceful no-result states. There has been no on-device performance measurement, live Drive upload, or Gaming Mode controller/hardware validation. Release acceptance still requires review, CI, device testing and a separately approved release with a GitHub-issued asset digest.

## Validation on this branch

- 52 Python unit/integration tests passed, covering synthetic upstream schemas, exact/mismatched App IDs, independent source failures/deadlines, robots restrictions, cache/response limits, hostile report text, local HTTP actions, config previews, backups/manual edits/restore, approved-file sync scope, native Valheim preferences, deck-user subprocess identity and update errors.
- Decky `npm run typecheck` and `npm run build` passed. Shell syntax checks passed.
- Chromium/Playwright Desktop smoke test passed for dashboard loading, default/uninstalled mode persistence, mocked Steam search, graceful source failures and escaped hostile report text. The reusable test isolates data and uses an ephemeral server port; it does not exercise the Steam Gaming Mode runtime.
- Local app/plugin ZIPs assembled. The original main/v0.6 updater accepted the v0.8 archive; a temporary v0.6 app upgraded, returned v0.8 plugin state, and rolled back to v0.6. The final archive was rechecked with the old validator.
- These are local checks, not evidence of a completed GitHub Actions run, published release, live third-party fetch, Drive upload or actual device benchmarking.
