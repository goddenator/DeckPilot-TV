# Stable / Preview updates — v0.8.3-preview.1

This is implemented development code for issue #5, not a published release or an on-device validation claim. The user-tested v0.8.1 layout and v0.8.2 controlled Play prototype remain in place. Steam's native Play is still untouched.

## On the Steam Deck

Open **DeckPilot → Settings → Updates**. Stable is the default. **Enable Preview → Confirm** opts into approved development prereleases; choosing either channel only checks/downloads, never installs or silently downgrades.

1. **Check for Updates** verifies and caches both components from the same release. You see the app/plugin versions and exact build commit. The background app checks every six hours; the plugin can check even when the old app cannot understand channels.
2. **Update App → Confirm** starts the existing SteamOS user service updater, saves the previous application, replaces only its three runtime files, restarts and checks its full build ID. Failed restart restores the previous files. An interrupted operation retains a persistent recovery snapshot and exposes **Recover Interrupted Update**. Game settings, saves, game backups, preferences and Drive configuration are never part of the replacement.
3. After the matching app is healthy, **Install Plugin in Decky → Confirm** snapshots the current plugin into user data, verifies the staged ZIP again, and copies a five-minute local installation link. DeckPilot opens Decky's Developer settings. Enable Decky's Developer mode once if necessary, paste into **Install from URL**, and accept Decky's warnings/installation confirmation. The exact label/route and clipboard behavior need hardware testing. If copying fails, a selectable link remains visible.

The plugin does **not** have a supported public installer API. The implementation uses Decky Loader's documented Install from URL feature, not private `DeckyBackend` methods, root writes, auth scraping or replacing plugin directories. Extra Decky paste/confirmation taps are required. It serves already verified bytes only on 127.0.0.1, under an unpredictable URL, for five minutes; there is no directory browser. Decky remains responsible for unloading, installation and reload. A prepared link is never reported as an installed plugin. Nothing touches other plugins.

**Restore Previous App** and **Restore Previous Plugin** are separate confirmed actions. Plugin rollback uses the same Decky installation confirmation. If Loader fails or the new plugin will not load, open the DeckPilot Desktop dashboard and choose **Prepare Plugin Rollback**, then paste that local link into Decky’s Developer settings. This recovery path uses the running app and does not depend on the plugin frontend. A trusted previous published plugin URL is the fallback if neither new interface starts. Unlike app recovery, Loader installation is not an atomic two-component transaction. App-first order and a version-mismatch warning prevent new profile/Play controls until both components match. The ordinary Steam Play button remains available. A same-version app repair is not offered automatically.

## First installation of this updater

An older installed plugin cannot discover this feature by itself. After the owner approves and publishes the first paired preview, use **Decky Settings → Developer → Install from URL** once on the Deck with the published plugin asset URL:

`https://github.com/goddenator/DeckPilot-TV/releases/download/v0.8.3-preview.1/DeckPilot_Decky_v0.8.3-preview.1.zip`

**That URL is not available until an approved release is published. Do not install an unpublished or unreviewed build.** No Windows ZIP download, file movement, terminal or paid service is needed. The new plugin bundles its user-space update client, so it can check/update an already installed older DeckPilot application before the older app knows about channels. It requires the existing app's user service; it does not install a fresh system service or request root access. The first bootstrap through old Loader cannot retroactively back up the plugin it replaces; subsequent updates snapshot the installed plugin before every handoff. Keep the last known-good published plugin URL for initial bootstrap recovery.

## Publication: owner approval required

Normal pushes/PRs run tests and upload build artifacts only. Tags no longer publish releases. No release, tag, environment configuration, label or merge was created by implementing this feature.

Before publication, configure GitHub Environments **deckpilot-preview-publish** and **deckpilot-stable-publish** with **goddenator as required reviewer**, and restrict who can edit those environments/workflows. This is available for this public repository without paid services. The workflow refuses publication if the required owner reviewer is absent; a newly auto-created unprotected environment is insufficient.

For an unmerged Preview, apply the explicit **deckpilot:publish-preview** label to the reviewed PR. The `pull_request: labeled` workflow freezes that PR's full SHA, verifies the environment protection and then waits for the owner's environment approval. Remove/reapply the label after new commits; publication rechecks the PR head after approval and fails if it moved or closed. This route permits approved preview releases without merging main. The separate manual dispatch route becomes available once this workflow exists on the default branch; it accepts an exact reviewed SHA and Stable/Preview selection. Nothing is published on ordinary pushes or simply opening a PR.

The protected job reruns Python, typecheck, frontend build and UI tests at the approved SHA. `tools/package_release.py` emits:

- `DeckPilot_TV_v<full-version>.zip`
- `DeckPilot_Decky_v<full-version>.zip` (includes `update_client.py`)
- `DeckPilot-Update.json` (repository, exact commit, channel, versions, size/SHA256 and protocols)
- `SHA256SUMS`

`tools/publish_approved.py` refuses non-Actions invocation, mismatched version/channel/commit/checksums, existing releases or tags. It creates a draft targeting the exact SHA, verifies GitHub's uploaded SHA256 digests for all four assets, then publishes. Failures leave an unpublished draft; repair deliberately or choose a new version. Preview requires `X.Y.Z-preview.N` and a GitHub prerelease; Stable requires numeric `X.Y.Z` and a normal release. Bump all source/app/plugin versions together for each new build; never overwrite a tag. CI builds clean checkouts, so the manifest commit corresponds to actual packaged sources.

## Trust and recovery limits

The update source is fixed to `goddenator/DeckPilot-TV`; no arbitrary repository, Actions artifact, draft or temporary third-party package is accepted. The client requires both paired components, exact full versions, schema 2/update protocol 1, allowlisted ZIP members and identities, bounded sizes, safe HTTPS redirects, GitHub asset digests and cross-matching manifest/checksums. Cached files and the captured approval token are checked again before installation. Channel changes invalidate approval. Returning from Preview to an older Stable requires an explicit downgrade confirmation.

GitHub HTTPS and digests provide source/integrity checks, not an independent developer signature or protection from a compromised repository/publisher account. The release manifest is trusted as owner-published metadata; it is not a GitHub attestation. No API key or paid API is required for public checks; unauthenticated GitHub rate limits/network failures are shown. An already verified staged build remains usable offline after a failed check. The feed scans up to 150 recent releases. Incomplete or incompatible latest channel releases fail closed rather than silently installing an older build.

## Validation and Steam Deck checklist

Automated coverage includes channel/draft selection, partial releases, fixed source/digests, corrupt downloads and cache, protocol mismatch, stale approval, downgrade consent, repeated update queue requests, app restart failure/rollback, persistent mid-replacement crash recovery, read-only plugin snapshot, unsafe ZIP paths, nonce-only loopback transport/expiry, UI app-first gating, channel cancellation, clipboard refusal and supported Decky handoff. Existing game/Drive/Play tests continue to run.

Still requires device/live testing: user `systemd-run`/D-Bus behavior on SteamOS, service health/restart and forced interruption/recovery, actual Decky URL paste/install/reload and rollback, plugin-file read permissions, controller focus/clipboard/Developer route, app/plugin mismatch recovery, Google Drive after updates, and the first owner-approved public release's real API/download assets. Cloud access to `api.github.com` currently fails at the proxy with `CONNECT tunnel failed, response 403`; mocked feed tests and local package/transport tests do not establish live release delivery. No new update feature is claimed hardware-tested.
