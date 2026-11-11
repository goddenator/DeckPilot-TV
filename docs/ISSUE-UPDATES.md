# Prepared issue updates — preview.5 stage

These are draft issue comments, not a claim they have been posted. This cloud environment currently denies `api.github.com` (the GitHub CLI returns Forbidden); public issue reads and Git pushes work. Allowing the API and a usable scoped write binding are prerequisites to posting. No issue should be closed on the basis of synthetic tests.

## Issue #8

Implemented an unmerged preview.5 update/recovery stage on the existing development branch/PR #3. Current official Decky source was inspected at `ffd103b9c1a4ce5bf305e7c0998eda6e05457dad`. Loader's installer utilities are internal; the public plugin API does not expose them. The supported user-facing Developer screen has a local ZIP picker starting at Home; URL autofill is not a supported contract.

New Update Everything flow waits for the actual app build to restart, prepares the verified plugin at Home → DeckPilot Updates → DeckPilot.zip, and sends the user to Decky's own file-picker/confirmation. No clipboard, direct GitHub download by Loader, long URL typing, Desktop Mode, manual download/extraction or live-plugin replacement is required by this new routine path. Installation is not reported complete until all approved plugin files and the running app match. Persisted receipts and approval state support panel/plugin reload; rollback uses the same prepared ZIP path. Queued rollback races, repeated cache hashing and inconsistent snapshots were corrected.

A one-time controller bootstrap from preview.4 can choose its existing verified private cache in Decky's Show hidden files picker, after app update and the old plugin-snapshot confirmation. This follows inspected upstream controls but still needs the user's actual Loader/controller acceptance. `docs/PREVIEW-5.md` contains the steps, failure cases and limitations. Keep #8 open pending that device test. No release, tag or merge has occurred.

## Issue #6

The preview.4 device evidence remains unresolved: ATS 270880 has 28 environment and executable permission denials and uncertain/exe-permission. This stage does not bypass ptrace/SteamOS checks, assume the processes unrelated, or claim the game closed. All existing proc/write/restore/dispatch safeguards and tests remain. The highest-priority delivery is Gaming Mode updates so subsequent detection work can be tested without repeated Desktop Mode switching.

Next: inspect available per-App-ID Steam/Decky state capabilities, add bounded redacted evidence and reconcile disagreements conservatively. Existing typed app-store globals are an investigation lead, not proof of a supported, tested closed-state authority. The actual Deck is the final acceptance test. Keep #6 open.

## Issue #7

No ATS/FFX optimisation success or support-count improvement is claimed in this update stage. ATS 270880's native config has five uniquely recognised keys and the checked Proton candidate is absent; that does not yet verify encoding, value ranges, writes or visible graphics effects. FFX still lacks its exact installed App ID and verified graphics format. Both remain advice-only, with zero game-setting writes from this stage.

Existing exact previews, original backups, manual-change protections, readback verification and restore remain tested. Next stages need safe format/value evidence and the #6 process barrier resolved before a writable per-title adapter; reusable three-mode consent comes after that. The full staged assessment is in `docs/IMPLEMENTATION-PLAN.md`. Keep #7 open; no release/tag/merge or device installation is performed.
