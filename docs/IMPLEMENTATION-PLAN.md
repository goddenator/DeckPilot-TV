# Reliability and usability programme

Continue on `feature/game-settings-research-v0.8`, PR #3. Published preview.4 is an immutable baseline. Deliver independently reviewed stages; ordinary commits/pushes are authorised, but merging, tagging, publishing, changing deployment protections and installing on the user's Deck are not.

## Current assessment

Repository inspection covers the app/CLI/dashboard, adapter and research code, Decky bridge and frontend, all test modules, installer scripts, update client, packager/publisher, approval guards, workflows, existing documentation, recent commits and issues #6–#8. The first implementation stage is an update-path audit, not a claim that every future phase is already audited or implemented.

| Requirement | Current state | Feasibility / next implementation |
|---|---|---|
| Gaming Mode paired updates (#8) | Paired digest verification, app update/rollback and plugin snapshots exist. Actual user reports URL/clipboard handoff failure and repeated Desktop Mode fallback. | Highest priority: unified review/app-first flow, automatically prepared local ZIP in a fixed visible home folder, Decky's existing Gaming Mode file picker, actual installed-file and running-app verification, retry/recovery. Decky still owns installation and confirmation. |
| Running detection (#6) | Tri-state bounded proc probe; actual Deck has 28 environment and executable permission denials. | Keep unknown blocking all writes/unsafe dispatch. Investigate per-App-ID Steam bridge evidence separately; typed/reverse-engineered Steam globals alone do not prove a supported, working closed-state API. Final acceptance requires the Deck. |
| Real modes / verification (#7) | Allowlisted Unreal settings and native Unity resolution, exact preview, original backups, manual-edit guards, readback and restore. Most installed titles remain unsupported. | Extend verified per-title adapters only with actual file/schema/value evidence and process safety. Never infer optimisation from preference selection or invented FPS. |
| ATS / FFX | ATS 270880 native candidate has five recognised keys; Proton candidate absent. FFX exact installed ID/format absent. | ATS needs actual schema/encoding and safe value ranges; FFX needs manifest ID plus graphics-only config evidence. Do not claim a working adapter from key counts. |
| Automatic dock detection | DRM advertised outputs are diagnosed; contexts are manual. | Add opt-in, debounced external-display suggestions; connection is evidence of display use, not proof of dock model or active 4K120/VRR. Profile changes must not silently apply files. |
| Compatibility scanner | Per-game adapter discovery and aggregate counts exist. | Add supported/partial/advisory/investigation categories from adapter capabilities and safe format probes, with bounded scans. |
| FPS/frame-time comparison | Opt-in, read-only attributable MangoHud summaries exist. | Require comparable measured sessions/context/mode; unknown attribution stays unknown. No fabricated comparisons. |
| One-time approval | Approval is bound to exact mode/context/file fingerprints. | Future consent must enumerate adapter revision/schema/keys and all three allowed modes; new files/format/adapter/context require fresh review, and manual edits revoke consent. |
| Actual settings verification | Write/readback counts and matching checkup exist. | Expand key-level outcomes and after-exit retention; file match never means a measured FPS gain. |
| Problem detection | Checkup, process reasons, update results and errors exist. | Add bounded local health summaries and explicit repair actions. Crash attribution needs actual evidence, not inference from a missing process. |
| Battery/thermal adviser | Missing. | Optional read-only supported sysfs/Decky sensor evidence, unknown states and advice only; no power-control writes. |
| Configuration history | Original backups and latest state exist; no browsable history. | Bounded per-game events with verification/restore eligibility, no saves or raw config exports. |
| One-button diagnostics | Local export/private opt-in Drive exist, with redaction and manual-only aggregate process/coverage probes. | Add update receipt/failure and schema evidence with review before upload. Keep credentials, configs, saves and raw process details out. |
| Better research | Three independent sources, provenance, context, confidence, bounded caches and offline labels exist. | Improve version/age/device matching and failure visibility; source reports remain advice, never executable adapter instructions. |
| Controller UI/reliability | Four main screens, focus handling and UI tests exist. | Stage updates first; then audit scrolling/focus, filesystem/cache cost and other runtime paths with targeted regressions and real controller acceptance. |

## Official Decky investigation (11 November 2026)

Inspected upstream `SteamDeckHomebrew/decky-loader` at `ffd103b9c1a4ce5bf305e7c0998eda6e05457dad` and the installed public `@decky/api` source. Loader's `frontend/src/plugin.ts` installer calls `DeckyBackend` utilities internally; it is not a public plugin installer export. No private callable, auth scraping, live-plugin replacement or DOM patch is permitted. Store update entries are registry-managed, not evidence DeckPilot has an approved Store listing or that its GitHub Preview channel is available there.

The supported user-facing Developer screen offers Install from ZIP and Install from URL. Its ZIP picker starts at the user's home and opens the selected local file through Loader's own installer. Its URL field is component-local state with no supported autofill contract. The verified route is `/decky/settings/developer`.

Sources:
- https://github.com/SteamDeckHomebrew/decky-loader/blob/ffd103b9c1a4ce5bf305e7c0998eda6e05457dad/frontend/src/components/settings/pages/developer/index.tsx
- https://github.com/SteamDeckHomebrew/decky-loader/blob/ffd103b9c1a4ce5bf305e7c0998eda6e05457dad/frontend/src/plugin.ts
- https://github.com/SteamDeckHomebrew/decky-loader/blob/ffd103b9c1a4ce5bf305e7c0998eda6e05457dad/frontend/src/store.tsx

## Stage 1: preview.5 scope

Implement real update orchestration and a clipboard-independent, network-independent Loader handoff after verified download. DeckPilot prepares `~/DeckPilot Updates/DeckPilot.zip`; the user selects that already-prepared ZIP in Decky's Gaming Mode picker and approves. No repeated manual download, extraction, file movement, URL typing, PC or terminal is needed. This is a controller-only fallback, **not** automatic plugin installation. The actual Loader/controller flow remains an on-Deck acceptance test.

Keep existing channels, checksums, app-first ordering, app/plugin backups, URL fallback, no-duplicate-operation guards and publication protections. Report completion only after exact plugin-file readback and matching running app identity. Retain useful state across frontend reload; stale/cancelled approvals must not queue another app installation. Add permission, symlink, low-space, wrong-file, stale-token, version mismatch, recovery, navigation and offline regressions. Run all Python/UI/publication tests, typecheck/build, dashboard smoke and package/update/rollback checks, then commit/push and inspect CI. Update issues without closing hardware blockers.

Subsequent stages follow the requested order: target-specific process evidence → real verified adapters/ATS/FFX → reusable approvals and dock detection → scanner/diagnostics → measurements/history/adviser/research → broader UI/performance audit. Urgent defects discovered in the delivered path are fixed immediately rather than deferred for optional features.
