# v0.8.3-preview.4 — issues #6 and #7

Prepared on `feature/game-settings-research-v0.8`. This is an unmerged review build, not a published release or a claim of hardware resolution. Existing previews remain immutable. The owner authorised committing and pushing the feature branch for CI. No merge, tag, release upload, issue closure or publication is authorised.

## Device evidence used

Read issue #6, including the 2026-11-11 physical-device follow-up, and issue #7 directly from their GitHub pages. Preview.3 on Steam Deck OLED / SteamOS / Python 3.14.6 scanned 423 processes and returned `uncertain/process-unreadable` for all eight samples. ATS is App ID 270880. Final Fantasy X's exact installed ID is absent from that evidence and is not guessed. The report counted 27 games, one native Valheim adapter, 26 unsupported games and zero backups. These observations establish a visibility blocker and a coverage gap, not a failed approved graphics write.

## Process changes

- Replace the combined unreadable bucket with fixed aggregate categories for ownership, stat parsing/read/permissions, environment, executable and Wine command identity, missing attributes, process reuse, limits and conflicting identities. Only categories/counts and a fixed explanation leave the probe; no PID, process name, environment, command line or path is exposed.
- Parse Linux stat fields explicitly, preserving non-UTF8 command-name bytes and embedded parentheses. Linux truncates `comm` to 15 bytes; known long helper names now match that truncation only with corroborating executable identity.
- Ignore kernel threads only with the kernel's PF_KTHREAD flag. Empty command lines, unreadable environments and helper-looking names alone never establish safety.
- A non-dumpable user's process can have a root-owned proc directory. Check kernel UID metadata in that case rather than silently skipping a potentially running game.
- Check identity after the final read. A missing executable/environment attribute on a still-live PID remains uncertain; only a vanished identity record is treated as an exit. Duplicate conflicting Steam IDs fail closed.
- Preserve all write/restore/dispatch barriers. Advanced Game Checkup explains the category and counts without a terminal. Manual exports include aggregate process and coverage evidence; automatic Drive reports omit it.

The cloud machine reproduced the old broad reason through denied environment followed by denied executable-link reads. This demonstrates the categorisation defect; it does **not** establish the cause on the Deck. Unknown executable identity still blocks operations. No unsupported Steam running-state API, permission bypass or catch-all closed fallback is introduced.

## Graphics behavior

Mode selection explicitly says **Preference saved — no settings were changed. 0 files changed.** The three mode names and screen structure remain. Checkup separates supported-file count, settings that currently match, and approved state. Review reports that no files have changed yet; approved application reports exact file-write and verified-readback counts. A mismatched or unreadable readback returns failure, retains the original backup and revokes earlier sync approval in the shared write path, including background synchronisation. A partial failed Apply also revokes earlier approval.

ATS has read-only checks for native and Proton `config.cfg` candidates. They report existence/status and the number of uniquely present known graphics keys, never values or private paths. A candidate is not a writable adapter. Final Fantasy X diagnostics take its actual ID from the installed manifest and explicitly flag missing format verification. These checks appear in Advanced and manual diagnostic export.

**No new ATS or Final Fantasy X writable adapter is enabled.** The issues provide neither a confirmed configuration layout nor a sanitized settings sample. Inventing an adapter from the game title would violate their requested safety requirement. Existing Unreal/native Unity adapters gain explicit outcomes and readback verification; the measured 26-game device support gap is not claimed to be fixed.

## Next adapter acceptance gate and three-mode workflow

For each title, establish the installed manifest ID and native/Proton variant, an existing config location, encoding/schema and exact graphics-only keys. Use a redacted graphics-only fixture reviewed against authoritative format documentation. Do not export or edit saves, profile credentials, arbitrary INIs, registry blobs or unknown binary files. Tests must cover malformed/duplicate keys, symlinks, read limits, context presets, exact preview, backup, readback, newer manual changes and original restore. Confirm visible effect after relaunch on the Deck before claiming support.

The current controller path is choose mode → Review & Apply → approve → verify local settings. Existing automatic sync remains limited to the approved mode/context/files and fresh closed-state checks. For a future setup-once workflow, initial approval should enumerate the supported adapter and all three mode key sets for that context; each mode change must still create a fresh local plan, check process state, preserve the baseline backup, reject newer manual edits, verify readback and expose rollback. A new or changed adapter/file/schema/context revokes that grant. This broader consent model is a design, not shipped behavior in this preview. Steam runtime graphics, TDP and Gamescope settings remain outside the adapters.

## Controller-only device validation after release approval

1. Install the paired app/plugin through the on-Deck Preview channel after the owner approves publication. Do not transfer Windows ZIPs. Check both show preview.4.
2. In Steam, confirm ATS shows **Play**, not Resume/Stop. Open its DeckPilot details → Advanced → Refresh Game Checkup. Record state, reason and aggregate counts; no terminal is required. If uncertain, use native Steam Play once and record whether it works. DeckPilot must not dispatch or edit while uncertain.
3. Exit ATS, wait for Steam's Play button, refresh again; repeat while the game is running and after exit. Confirm exactly one launch when a genuinely closed state permits controlled Play.
4. Repeat for Final Fantasy X, recording its displayed actual App ID. Do not infer the ID from a similar title.
5. Selecting any mode must say preference only / 0 files changed. ATS and FFX remain advice only in this preview. Review a manual diagnostic export containing the new aggregate coverage/probe results before sharing it. Automatic Drive uploads omit these new fields.
6. For the existing supported Valheim config, only when visibility is closed: Review & Apply, inspect exact keys, approve, confirm readback count/checkup, then restore. Verify a newer in-game/manual edit is protected. Do not treat matching resolution as a measured performance gain.

Keep issues #6/#7 open pending device evidence and verified adapters. CI, publication approval and hardware acceptance are separate checks.

## Local validation results

- 157 Python tests passed (including process faults, settings outcomes, manual-change/restore/update regressions and local HTTP behavior).
- 57 Playwright UI/controller tests passed under Node 22.23.4 with Chromium and Decky/Steam shims.
- 9 publication-guard tests passed. TypeScript checking, Rollup build, shell syntax and `git diff --check` passed.
- The production `serve` command started with isolated data; dashboard and `/api/state` returned the expected preview.4 `build_id`. The separate Chromium dashboard smoke test passed with no JavaScript errors.
- Local paired ZIPs were assembled and checked against component sizes/SHA256 manifests and ZIP integrity. Rebuild after committing and verify that suite metadata names that exact source commit before any separately approved publication.
- Check GitHub Actions separately for the exact pushed commit. Local checks do not establish remote CI success. No actual Steam Deck graphics-effect test, live Decky runtime test, merge or publication is implied.

## Review follow-up

The final review covered the full diff, process ownership/parser/error paths, permission and PID races, mutation/backup/readback/sync behavior, diagnostic privacy, UI outcome messages, version/lockfile alignment, package contents and publication boundaries. It found and corrected bounded-read enforcement, stat-error attribution after a denied environment, a completed scan exceeding its deadline, stale UI support messages, inappropriate closed-state blocker wording, the packaged README link and retained sync approval after failed readback. Six new regressions extend the original 217 tests to 223; no original test was dropped.

The review and synthetic tests cannot prove SteamOS process visibility, Decky hardware behavior or safe new per-title adapters. Issues #6/#7 remain open pending on-device results. There are no changes to publisher permissions, workflows, dependencies or lockfile resolutions (only the root package version changed).
