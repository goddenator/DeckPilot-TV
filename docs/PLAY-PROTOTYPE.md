# v0.8.2 controlled Play prototype

**Working implementation: DeckPilot’s own Play button. Steam’s native Play button is not intercepted.** The user-tested v0.8.1 Home / Find Games / Game Details / Settings layout is preserved. This is an unreleased opt-in development prototype, not an on-device launch validation claim.

## Try it

1. Install the matching reviewed v0.8.2 app and Decky plugin development artifacts. No release is published by this work. An older backend has no controlled-Play capability and the new control stays unavailable.
2. In **Settings → Advanced → Play-time recommendations**, select **Play recommendations · Off**, read the prototype notice, then **Enable Play recommendations**. Default is Off; an old ignored native-interception flag cannot enable it.
3. Find an **installed Steam game**. In Game Details choose **Play with DeckPilot**. The normal Steam Play button continues to work independently.
4. Choose **Best Graphics**, **Best Performance**, or **Balanced** in the prompt. Mode selection here changes no files or saved game mode on its own.
5. Choose an action:
   - **Apply & Play** opens the exact allowlisted file locations and before/after changes. **Approve & Play** backs up and applies that specific mode/context/content-bound preview, then requests launch. Unsupported/changed/running games never get a false apply action. No downloaded report instructions become settings or commands.
   - **Play Without Changes** requests ordinary launch with zero settings operations from this flow.
   - **Don’t Ask Again** remembers that Steam App ID, then requests launch without settings changes. Later DeckPilot Play presses bypass the prompt. **Advanced → Ask again for this game** resets it.
   - **Cancel**, Back, or closing the panel before approval abandons the controlled launch. It changes no game files and issues no launch request.

Before approving, every editable key and its old/new value is visible; this launch review does not hide the diff under Advanced. Original backups, manual-edit preservation and restore use the existing tested adapter pipeline. Once an approved write begins, cancellation is disabled until its result is known; the UI does not pretend it can undo an in-flight mutation. Approved changes may finish if the plugin unloads, but unload invalidates a queued automatic launch.

## Cache and failure behavior

The new `play-plan` command reads only the installed Steam manifests, selected profile, local checkup and existing research cache. It never calls Steam Store, publisher APIs, update downloads or rclone. Get Advice remains a separate, explicit action for populating the cache before play. Missing cache yields **Suggested starting settings**, not “best settings found”. Cached context, source, confidence, resolution/FPS metadata and staleness are labelled; targets are not claimed as measured performance. Balanced remains the conservative starting suggestion.

Read-only plan/preview operations have a three-second UI deadline. If local advice is unavailable before any mutation, a known installed target can launch once without changes. Unsupported games retain advisory/Play Without Changes. Missing Steam launch API, unknown/non-Steam IDs, an already-running game, or changed game/profile produce a clear native-Steam fallback without edits. Ordinary Steam launching is never patched, cancelled or blocked, whether the feature is disabled, unsupported or broken.

Mutations are deliberately **not** raced against a timer that would start the game while a delayed write might still occur. The deck-user bridge waits for the command to complete or confirms termination at its existing command deadline. A known apply rejection returns to the prompt and permits an explicit unchanged/further-changes-free launch. A transport failure with unknown apply outcome blocks automatic launch/retry in that controller session; check settings and use Steam directly. Partial approved changes, if an individual file fails, remain backed up and are reported by the existing apply result.

The launcher calls Steam’s existing `SteamClient.Apps.RunGame(appid, '', -1, 100)` using the captured positive 32-bit installed App ID and the standard library-details/default launch choice. It never writes Steam launch options, game saves, arbitrary Proton environment variables, or shell commands. `RunGame` returns no reliable process-start acknowledgement, so the UI says **launch requested**, not “game successfully started”. Steam still handles its normal launch dialogs/options. Actual SteamOS behavior must be tested on the Deck.

One shared controller ignores repeated presses while a request/prompt/review is active, marks dispatch before calling Steam, and retains a short duplicate-attempt cooldown. A throwing/rejected/hung launch is never automatically retried and stays guarded in that controller session. Unknown apply outcomes are also guarded. Cancellation invalidates late read callbacks; unload invalidates pending launch dispatches. No game-action observer, native Play patch, cancellation callback, relaunch callback or launch-option wrapper is registered, so there is no cancel/relaunch recursion path.

## Why native Steam Play is not supported yet

`RegisterForGameActionStart` runs after Steam has begun a launch; it is not a safe asynchronous pause gate. The previously investigated cancel-then-relaunch technique requires device validation of action IDs, running detection, cancellation timing, one-shot bypasses, focus and recovery. This task explicitly permits a DeckPilot-controlled button as the first testable alternative, so the prototype uses that path instead of cancelling ordinary Steam launches on an unverified hook.

## Tests and on-Deck checklist

Automated tests cover local-only cached plans, exact App ID/context matching, opt-in/dismissal persistence, command wiring, exact preview and original backup/restore, disabled/running/changed-file rejection, unsupported/missing APIs, launch exceptions/rejections/timeouts, repeated presses/reentry, cancellation/late callbacks, explicit approval, unknown apply results and unload/relaunch prevention. Browser tests exercise the production plugin entry and component tree with Decky/Steam/RPC shims; they do not claim to emulate Steam controller internals.

On the Steam Deck OLED:

- Confirm the four-screen layout is unchanged and the feature starts Off. Native Steam Play must work while off, on, with DeckPilot unavailable, and after a plugin reload.
- Enable it and use an installed game’s DeckPilot Play button. Test all three choices using D-pad/A/B, and all normal Steam launch-option dialogs. Verify the exact intended App ID opens.
- Cancel before approval and verify no files or launch change. Test Play Without Changes, Don’t Ask Again, persistence across reload and reset in Advanced. Uninstalled and non-Steam shortcuts must not get this control.
- On a compatible game, inspect the full diff, approve, verify backup and actual settings, then restore from Advanced. Keep saves unchanged. Test changed files and a running game: no overwrites.
- Press Play repeatedly, close/reopen the panel during reads, and test a stopped backend. No double launch or delayed launch after cancellation should occur. An unknown apply/launch failure should advise checking Steam rather than retrying automatically.
- Repeat offline after caching advice. No publisher/Steam HTTP request should delay this prompt. Hardware performance, native Steam interception and actual RunGame behavior remain unverified until these checks pass.

Local validation for this change: **83 Python tests** and **42 Playwright-run tests** (19 controller tests and 23 browser UI tests), TypeScript check, Rollup build, Desktop dashboard smoke, shell syntax checks, and local app/plugin packaging passed. The original v0.8.1 updater accepted/installed the v0.8.2 app ZIP and rolled back in a temporary installation. Actual RunGame execution, Steam launch dialogs and controller focus still need the on-Deck checklist; mocks are not hardware evidence.
