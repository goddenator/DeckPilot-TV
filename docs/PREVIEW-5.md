# v0.8.3-preview.5 — Gaming Mode updates and recovery

Stage 1 of [the implementation programme](IMPLEMENTATION-PLAN.md), on the existing feature branch/PR #3. Preview.4 is the published baseline reported by the owner. This is a new, unmerged review build; it is not published or installed on the Deck. No tag, release change, deployment-protection change or private Decky installer call is part of this work.

## Delivered

**Check for Updates → Update Everything → Review/Confirm → wait for app restart → Open Decky Installer → choose prepared ZIP → approve in Decky → return and Verify Installation.**

The app updates first through the existing verified user-service transaction and rollback snapshot. DeckPilot waits for the *running* exact build identity, not just version text on disk. It then automatically prepares the verified plugin ZIP at **Home → DeckPilot Updates → DeckPilot.zip**. No routine manual download/extraction, file movement, long URL typing, clipboard, Desktop Mode, PC, phone or Konsole is needed. The final ZIP selection and confirmation belong to Decky; Update Everything does not pretend to bypass them.

Current official Loader source exposes Install from ZIP through its Developer screen and a picker starting at the user's home. The installer callable used internally by the Loader is not a public plugin API. Evidence and pinned upstream links are in the implementation plan. A Store listing could simplify installation later, but this work neither submits a listing nor invents Preview support in the Store.

Preparation saves the current plugin as a rollback ZIP, creates a bounded per-file verification receipt and never writes into the installed plugin directory. The visible folder is marked as application-owned; symlinks, unmanaged destination files, unsafe ZIPs, changed cached bytes, stale tokens, low space and an unhealthy/mismatched app block preparation. Snapshot files are reread to reject a plugin changing during capture.

After Loader installs/reloads the plugin, verification compares all expected plugin files to the approved archive and checks the actual running app build. A prepared archive, matching package version alone or mismatching bytes never counts as success. **Verify Installation** also supports a first installation from the already-verified cache without an earlier pickup receipt. Status, recovery and the receipt survive panel/plugin reload. A remembered exact approval may resume preparation for up to 30 minutes; the app-wait stage times out after three minutes without automatically queuing another installation.

## Recovery and confirmed fixes

- **Restore Previous Plugin** prepares the saved ZIP through the same visible-folder path. Loader still confirms installation. The replaced plugin is retained as the next rollback snapshot. App rollback/recovery remains a separately approved transaction; mismatched app/plugin versions are never called a completed paired update.
- App rollback now records its queue state under the operation lock. Repeated rollback requests, app updates and channel changes cannot race a queued rollback. A queue failure preserves snapshots and gives a retryable error.
- Routine status polling no longer rehashes both cached ZIPs every three seconds. Explicit download/install/prepare/bootstrap verification still checks the full approved bytes. Polling has backpressure and ignores responses superseded by a user action.
- `/api/identity` returns only version/build ID under the existing loopback Host restrictions. Health checks can use it without rescanning the library; older apps fall back to their existing state endpoint.
- Diagnostics now include fixed update outcome/recovery/backup/prepared-version indicators, without paths, nonces, tokens, checksums, raw receipts or configuration contents. These do not include raw process data. Prepared does not imply installed.
- Separate app/plugin actions and the old confirmed URL handoff remain under **Separate update actions** for compatibility. The normal new route does not depend on them.

## One-time transition from published preview.4

An older plugin cannot display new controls before Loader installs the new plugin. After separate owner review/publication approval, the first transition can use preview.4's existing verified cache entirely in Gaming Mode:

1. In preview.4 Updates, enable Preview if needed, Check for Updates, review and approve **Update App**. Wait for the app update to complete.
2. Use preview.4's **Install Plugin in Decky → Confirm** once. Continue only after preparation confirms readiness: this preserves the current plugin snapshot even if URL autofill is unusable. Stop on any backup or permission error; do not bypass a failed snapshot. Do not report the plugin installed at this point.
3. In Decky Settings → Developer → **Install from ZIP**, turn on **Show hidden files**. Starting at Home, choose `.local → share → deckpilot-tv → updates → suite-cache → 0.8.3-preview.5 → DeckPilot_Decky_v0.8.3-preview.5.zip` and approve Decky's confirmation. This is the ZIP the app already downloaded and verified; do not download or extract anything manually.
4. Reopen DeckPilot → Updates → **Verify Installation**. The new helper checks the approved cache against the installed files and the running app.

This bootstrap follows the inspected current Loader's file-picker controls. **It still requires testing on the user's actual Loader version and controller.** It is more navigation than later updates, which use the visible fixed folder. If the user's Loader differs or disallows that path, report the exact blocker rather than claiming the transition works. No code here installs itself on the user's Deck.

## Real Steam Deck acceptance checklist

After the owner separately approves and publishes this build:

1. Perform the Gaming Mode bootstrap above from preview.4. Confirm exact app/plugin versions and successful installed-file verification.
2. For a subsequent separately approved build, use Update Everything. Confirm one app request, visible progress, app restart before plugin preparation, and one native Loader confirmation. Cancel the review first and verify that nothing starts.
3. Test ZIP selection, Back/Cancel, focus, scrolling and text at the Deck's actual resolution. Ensure Developer mode can be enabled once entirely in Gaming Mode. Deny clipboard access: the normal path must still work.
4. After a verified download, disconnect the network and prepare/install the cached plugin. The native installer reads a local file. Test low disk space/read-only pickup safely without deleting personal files; errors must preserve the running installation and old ZIP.
5. Cancel Loader installation and reopen Updates: it must remain pending. A same-version wrong bundle must fail readback. Reopen the panel after an app restart and confirm the app request is not duplicated.
6. Exercise app recovery and plugin rollback separately using approved test builds. Require matching versions and real running-app/file checks before Done. Returning to an older plugin also returns its older UI; do not infer new verification features exist in preview.4.
7. Export/review diagnostics. Confirm useful update status and absence of paths, credentials, raw config/save/process data. Drive remains optional.
8. Recheck ATS Advanced Game Checkup without changing any settings. The 28 `environment-permission`/`exe-permission` failures remain a real unresolved blocker; do not infer closure, apply settings or claim a SteamOS fix from these update changes.

## Remaining programme work

Issue #6 is unresolved: the actual Deck's ptrace-controlled proc reads are denied. No permission bypass or invented Steam API is added. Typed Steam app-store globals are investigation leads, not a verified closed-state authority for writes.

Issue #7 is unresolved for ATS and FFX: ATS 270880 has a native five-key candidate, but safe schema/value/write evidence is still missing. FFX's exact installed App ID and graphics configuration are still missing. Both remain **Advice only — no game settings changed.** No FPS gains, settings effects or improved support count is claimed.

The ten requested features are assessed in the implementation plan. This stage improves updates and update diagnostics; it does not claim automatic dock switching, reusable multi-mode consent, full library classification, comparative benchmarks, crash attribution, history, battery/thermal advice or a new research system are delivered. Subsequent stages retain the requested priority order and separate review/version boundaries.

## Validation record

Local validation passed: **175 Python tests, 65 UI/controller tests, and 9 publication safety tests (249 total)**, with no skipped/failed tests reported. TypeScript checking, Node 22 build, shell syntax and the Chromium dashboard smoke test passed. Paired package identities, inner manifests, all SHA256 entries, current and preview.4 updater validation, a real temporary-filesystem app upgrade/rollback preserving preferences, and reproducible packaging passed. Exact commit/CI links are reported with the delivered stage. Full Python, UI/controller and publication safety suites, TypeScript checking, build, shell checks, dashboard smoke, package manifests/digests, updater validation and repeatable packaging are required before pushing. Simulated Loader tests exercise real ZIP/filesystem handling but do not emulate SteamOS permissions, the native Decky installer, actual controller focus or graphics effects. No hardware claim follows from passing them.

GitHub issue comments are prepared in [ISSUE-UPDATES.md](ISSUE-UPDATES.md). API writes are currently blocked by this cloud environment’s network policy; they must not be described as posted.
