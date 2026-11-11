# v0.8.3-preview.6 — native ATS effects and actionable game-state evidence

Unreleased work on `feature/game-settings-research-v0.8`, PR #3, based on published Preview.5. No merge, tag, release publication or installation on the user's Deck is performed. Preview.5's Update Everything, native Decky ZIP confirmation, installed-file verification and rollback code remain unchanged.

## What is and is not fixed

A conditional **native ATS graphics adapter** now previews, applies and verifies three real settings through the existing backup/manual-change/restore transaction. It does not change resolution, rendering scale, fullscreen, Steam options, power controls or saves, and does not promise an FPS target. Native SteamOS graphics effects still require a device test.

**Issue #6 is not established fixed.** The actual Deck's 28 environment/executable denials still cannot safely be treated as unrelated. All write, restore and controlled-launch guards retain the existing uncached proc tri-state policy. No Steam UI observation, user-selected Play/Stop label, cgroup or stored diagnostic record grants permission to write or dispatch.

## Official SCS verification

Successfully fetched over verified HTTPS on 11 November 2026:

- [SCS configuration variables, revision 5727](https://modding.scssoft.com/index.php?title=Documentation/Engine/Configuration_variables&oldid=5727), last edited 17 October 2025.
- [SCS game user path, revision 5162](https://modding.scssoft.com/index.php?title=Documentation/Engine/Game_user_path&oldid=5162).

SCS specifies Linux user data under `~/.local/share/<game_name>` and distinguishes global `config.cfg` from profile settings. It explicitly defines `g_veg_detail` as integer 0/1/2 (low/medium/high), and `r_cloud_shadows` / `r_sunshafts` as integer enabled switches. Their supported boolean values are restricted here to 0/1. `r_scale_x/y` are documented floats but no usable bounded range is specified. The previously observed `r_mode_width/height` keys are absent from this reference; SCS instead documents `r_mode`. None of those resolution/scaling keys are edited in this adapter.

| Mode | Vegetation | Cloud shadows | Sunshafts |
|---|---|---|---|
| Best Graphics | High (2) | On (1) | On (1) |
| Balanced | Medium (1) | Off (0) | On (1) |
| Best Performance | Low (0) | Off (0) | Off (0) |

These are documented-key starting presets, not benchmarked optimal values. Both Docked and Handheld use these limited effects presets; display settings remain unchanged.

### Runtime eligibility and safeguards

The adapter requires App ID 270880 in its exact installed manifest, a single safe install directory, a regular native `bin/linux_x64/amtrucks` ELF executable, no Windows executable in the corresponding depot, the existing native `config.cfg`, its SCS-style signature, `r_device "gl"`, and exactly one valid instance of each managed key. Unknown/mixed/Windows-only layouts, missing or ambiguous keys, unsupported values/casing/encoding, BOM/UTF-16 and symlinked paths remain unsupported. The native depot and config are evidence for this scoped adapter, not proof of custom Steam launch-option behavior. Custom launch variants need separate verification.

Only the existing three key values change; order, whitespace, comments, CRLF and unrelated settings are preserved. Preview binds the exact file/mode/context. Backups precede replacement; fresh process checks, manual-edit hashes, readback verification, sync-grant revocation on failure and original restore remain. A running/uncertain state blocks all game configuration writes even when all ATS schema checks pass. The user sees **partial support: vegetation/effects only; display resolution and scaling unchanged**.

The earlier five-key candidate does not prove these additional three keys or native-depot conditions. Preview.6's Advanced checkup reports each condition so a failed eligibility check has a concrete next step instead of guessed edits.

## Running-state investigation and new diagnostic workflow

The installed `@decky/ui` 4.16.5 types describe `appStore.GetAppOverviewByAppID`, its initialized flag and local display status, and `SteamUIStore.RunningApps`. Those are reverse-engineered Steam UI globals, not a documented, hardware-verified closed-state authority or a public per-game running-state API. SteamClient's overview-change callback uses protobuf data; no permission bypass, launch observer or invented closed-state endpoint is added. Missing getters, exceptions, initialization, exact App ID mismatch and malformed/oversized lists are handled explicitly.

**Game Details → Advanced → Record game evidence** asks what Steam currently shows (Play, Stop/Resume, or unsure), takes a read-only selected-App-ID UI observation and one fresh kernel scan, saves up to 12 bounded paired records and creates a real private local diagnostic ZIP. Advanced shows the comparison immediately. A mismatch remains diagnostic-only; the controller does not auto-launch or modify files from it.

For denied reads only, the explicit diagnostic scan additionally categorises readable kernel UID/tracer and cgroup evidence: same/mixed credentials, traced/not traced, target/other/no game scope, or unavailable. These are aggregate categories; they neither identify a process nor prove a different game's scope cannot contain relevant work. No PID, UID value, process name, command line, environment, cgroup path, other-game ID or account/client identity is exported. Mutation guards do not perform these extra probes. Observations are snapshots and can race; they do not guarantee closure.

The selected-game action reuses its one proc snapshot when building the report. Adapter discovery is reused within checkup/report generation rather than repeated for every adapter count. No stale closed-state cache is introduced.

### Privacy and reliability fixes

The automatic Drive path previously called the process-inclusive report generator despite the documented restriction. It now requests an aggregate-only report and removes manual process/graphics/evidence fields even if passed a richer report accidentally. Paired history and selected graphics evidence are included only in manual exports/explicit manual uploads after opt-in. The private fixed Drive destination and off-by-default opt-in are preserved.

Local report replacement is now atomic with a private temporary file/fsync, preserves the previous ZIP on failure and rejects a symlink destination. Native ATS encoding changes at the final write guard are protected like other manual edits.

## Final Fantasy X investigation

The [official Steam Store response for 359870](https://store.steampowered.com/api/appdetails?appids=359870) identifies **FINAL FANTASY X/X-2 HD Remaster**, Windows-only. This verifies the catalog identity, not what is installed on the user's Deck. The next selected-game evidence record captures the actual manifest App ID; no ID is assigned from the title.

The configuration schema remains unverified. PCGamingWiki presented an access challenge; no challenge was bypassed. Only read-only launcher INI candidate checks are added for the verified App ID, under the actual install directory or its Proton Documents path. The report distinguishes absent, unsafe/symlinked, oversized, text/INI-like and binary/UTF-16 candidates without exporting contents, section names or private paths. Candidate paths are investigation hints, not authoritative game configuration mappings. No FFX file is edited and no binary/settings/save format is guessed. **Advice only — no game settings changed.**

## Gaming Mode-only device checklist (after separate release approval)

1. Update the paired components through Preview.5's **Update Everything** / Decky prepared-ZIP flow. Reopen Updates and verify app/plugin Preview.6 match. No Desktop Mode, PC or terminal is required by this workflow.
2. In Steam, confirm ATS shows Play. Open ATS → Advanced → **Record game evidence → Steam shows Play**. Record again while ATS is running using Stop/Resume, then after exiting when Play returns. Use native Steam Play; never force a DeckPilot launch when uncertain. Repeat the same three observations for FFX. Each action saves the local report and retains the previous observations.
3. Review ATS's native/manifest/OpenGL/schema checks in Advanced. If any are unconfirmed, report the evidence; do not add/rename keys or change permissions to enable support. If process visibility remains uncertain, confirm Review & Apply blocks changes and stop the application test there.
4. **Only if the backend genuinely reports closed and the ATS adapter is eligible:** review each mode's exact three-key diff, approve, check the verified-file result, launch natively, inspect vegetation/effects in the game's menu/scene, exit and refresh checkup. A file match is not a measured FPS improvement. Test original restore while closed, and confirm a newer in-game/manual edit is protected.
5. Review the local diagnostic ZIP before optionally using **Upload latest diagnostics** to the already-connected private Drive. Automatic uploads omit these manual details. Report missing Steam UI capabilities, schema/depot failures and disagreements, rather than screenshots or raw process/config dumps.

If rolling the app back to Preview.5, restore ATS settings first when safely closed if desired. Preview.5 does not know the new ATS adapter; backups remain on disk, but restore of this new adapter requires Preview.6 again. Do not bypass uncertain-state safeguards to perform that restore.

## Validation

The complete original regression suite is retained, including Preview.5's Gaming Mode updater, recovery and rollback cases. New tests cover 28 denied processes, scope ambiguity, diagnostic-only Steam observations, exact App ID binding, privacy/manual-only uploads, native/Proton layouts, missing/duplicate/invalid ATS keys, encoding/symlink/launch races, exact preview, readback, backups and restore. UI tests use Steam/Decky shims; actual Loader, SteamOS running detection and graphics effects remain hardware acceptance gates. Exact counts and CI links are reported with the delivered commit.

Local validation: **194 Python + 70 UI/controller + 9 publication-safety tests = 273 passed**, with no failures/skips reported. Typecheck, Node 22 build, shell checks, Chromium dashboard smoke, paired ZIP identities/manifests/SHA256, reproducible packaging and a temporary-filesystem Preview.5→Preview.6 app upgrade/rollback preserving preferences passed. The public Preview.5 release and tag were verified to target base commit `2bd993fe6cff9103ccb9fe7360809236e1baaba1`. GitHub Actions must be checked separately for the pushed Preview.6 commit; hardware remains unverified.
