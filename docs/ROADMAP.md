# DeckPilot development roadmap

This branch is an unreleased v0.8.3-preview.2 development build for PR #3 and the redesign feedback in issue #4. No release or hardware readiness is implied.

## Shipped in this development branch

- Home, Find Games, Game Details, Settings, with secondary Sources and Advanced pages. Large controls, short labels, paginated library, keyboard focus retained after saving, and explicit loading/empty/error states.
- The same three modes. Separate manually selected Docked and Handheld preferences, including uninstalled games. Profile switching does not edit files or infer that a connected display is active.
- Game Checkup checks actual local settings, approval scope, running status, manual changes, and whether an original can safely be restored. “Ready” means the approved local preset matches, not that a benchmark passed.
- Preview then approval, backups, hash rechecks before writes, protected manual changes, atomic restore, and explicit restore confirmation under Advanced.
- Existing Unreal adapter plus native XML resolution-only support for Valheim and Hollow Knight. Unknown formats remain advisory. No save, launch-option, registry, TDP, display or VRR writes.
- Independently attributed reports with display-context ranking and evidence confidence; retained offline data up to 30 days, labelled as cached/stale. Confidence measures matching evidence specificity and recency, not a probability of reaching FPS. Balanced remains a conservative starting recommendation, not a claim to have computed optimal game settings.
- Optional read-only analysis of existing, attributable MangoHud FPS and real frame-time samples (off by default). This does not start recording, learn settings automatically, or upload raw measurement files.
- Updates recheck GitHub digests at approval/installation, freeze the approved ZIP, serialize operations and recover from late record failures. Profile recovery metadata protects inactive preferences when an older app rewrites legacy fields after rollback. Drive uploads are serialized across service/Decky processes, do not hold the game-settings lock during the network request, and completing an in-flight upload cannot re-enable a disabled opt-in. Paired Stable/Preview updates are implemented in [the update guide](UPDATES.md); plugin installation still requires Decky confirmation and hardware validation.

## Next: experimental Play-time recommendations

**Update:** the [v0.8.2 controlled Play prototype](PLAY-PROTOTYPE.md) is implemented and opt-in, using DeckPilot’s own Play button. Native Steam Play interception remains unimplemented and unregistered. The following native-hook investigation and later acceptance gates remain relevant.

### Investigation

The installed `@decky/ui` Steam client type declarations expose `RegisterForGameActionStart`, `CancelGameAction`, and `RunGame`. The start callback is a notification after Steam has begun the action, not a synchronous pause API. Awaiting research or previews in it races the launch. Patching a void-returning `RunGame` with a synchronous patcher does not create an asynchronous gate.

A community candidate is [RomM Tender ADR 0015: cancel then relaunch](https://github.com/danielcopper/romm-tender/blob/main/docs/adr/0015-single-launch-gate-cancel-then-relaunch.md). Its documented errata include game-ID/App-ID differences and stale running-game detection. These are relevant warnings about integration difficulty, not proof that the mechanism is reliable for DeckPilot or the user's SteamOS/Decky build. No upstream code has been copied.

The lower-risk first experiment is an **opt-in DeckPilot-controlled Play button**, before considering native Steam interception. It should use an injected launcher interface with mocked tests, then on-device validation. No launch-option wrapper, arbitrary command, process kill or save modification is acceptable.

### Required dialog and safeguards

1. Default Off. Present an explicitly experimental On/Off choice only when the tested path exists; do not offer a switch that pretends the current build intercepts launches.
2. Use previously cached exact-App-ID evidence without waiting on Internet requests. Say “Suggested starting settings” if there is no verified matching evidence.
3. Offer **Apply & Play**, **Play Without Changes**, and **Don't Ask Again** for that game. Keep the three modes. Show resolution/FPS targets only when sourced and label targets separately from measurements. “Not Now” can cancel only an explicitly controlled launch where that behavior is real.
4. Apply & Play must show the concrete local preview and require approval, back up first, recheck that the same game is closed and files are unchanged, then launch once. Unsupported games offer View Suggestions / Play Normally, never a false Apply action.
5. Decline/dismiss means no settings changes. Remember dismissals per App ID, with a reset option in Advanced. A later materially different recommendation must not silently overwrite that preference.
6. Missing APIs, ambiguous IDs, non-Steam shortcuts, already-running games, exceptions and timeouts must leave ordinary Steam launches alone. Do not cancel anything until the fallback/relaunch path is known usable.
7. A cancel/relaunch experiment requires synchronous eligibility checks and cancellation before asynchronous work, an expiring one-shot bypass token per exact game/action, duplicate-Play protection, exactly-once launch recovery, unload cleanup, modal focus recovery and suspend/resume testing. Never repeatedly cancel a relaunch. No global hook should ship enabled before those tests pass on hardware.

## Later optimisation work

- Validate the two native Unity adapters and compatible Unreal configs on the target Steam Deck OLED before expanding to more titles. Add a game only with known file format, known harmless keys, fixtures, preview, backup and restore tests. Unsupported games must remain advisory.
- Capture optional, consented measurement sessions with exact App ID, game version, Docked/Handheld context, resolution, preset, duration, timestamps and repeatable gameplay. Only then explore controlled before/after comparisons or recommendations from learning. Do not mix generic MangoHud logs, caps and achieved performance. Any learned change still needs local preview and approval.
- Investigate display/session detection separately from advertised connector modes and VRR capability. Until verified, selection stays manual and active VRR stays unknown.
- Preserve independent publisher provenance and schema contracts; validate live robots/API compatibility when access is available. Better evidence does not authorize downloaded instructions to become commands/config writes.
- A future Decky plugin update assistant needs an approved, digest-verified plugin package and installation through supported Decky mechanisms, with compatibility checks and rollback. This build only links to reviewed releases; it never silently installs a plugin ZIP.

## On-Deck review checklist

1. Preserve a backup of the installed app/plugin before testing this unreleased build. Install app and plugin together so the new plugin sees backend schema 2. An older app shows an update message and profile controls stay disabled.
2. In Gaming Mode at 800p, use only D-pad/joystick and A/B through Home → Find Games → Game Details → Settings → Advanced. Confirm focus stays on the selected mode after saving, virtual keyboard works, long names/empty search/errors scroll/read correctly, and Back is predictable. Repeat docked on the TV.
3. Confirm ordinary Steam Play is unchanged with the plugin loaded, unavailable, reloaded and offline. No native Steam interception, cancellation, global hook or background launch should occur. The new prompt appears only after an opted-in DeckPilot Play press; use the prototype guide for those checks.
4. Save different Docked/Handheld defaults and per-game modes for installed and uninstalled games. Switch profiles: no file should change. Preview, cancel, then separately approve while closed. Start a game during preview/apply: it must not be edited while detected running.
5. Test one compatible Unreal config and each native Unity XML adapter. Check unrelated keys and game saves remain untouched. Make a manual change; Checkup must protect it. Restore an unchanged managed file and verify later sync does not reapply. Missing backups must not report Ready.
6. Read live source reports, compare exact App IDs, dates and display context. Disconnect Internet after caching: retained reports must say offline/cached and confidence must downgrade for stale data. A first-time offline lookup must clearly fail without blocking preferences.
7. Opt into existing FPS logs only if desired. Verify attribution and units against known CSV samples; a similarly named game must not inherit the samples. No recorder starts and no automatic tuning takes place.
8. Review a local diagnostic ZIP before enabling Drive. Confirm exactly one private `DeckPilot Diagnostics/DeckPilot-Latest.zip` is overwritten; no public link is created. Disable uploads and verify new uploads stop (an already-started upload may finish without re-enabling uploads). Live OAuth/upload remains untested in cloud.
9. On a separately reviewed release, test automatic verified app download → explicit install approval → healthy restart → rollback with both profile preferences and all game backups preserved. Verify a changed ZIP is rejected. Plugin updates must require separate manual approval.

Release acceptance remains review, green CI for the exact head, on-device checks, a separately approved tag/release with GitHub-issued digest, and installation/rollback validation. No merge, tag or release is part of this task.
