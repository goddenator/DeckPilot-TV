# DeckPilot TV v0.6 — Steam Deck OLED, docked 4K/VRR TV

**Experimental prototype — not yet hardware-tested on a Steam Deck.** Designed for the official Valve dock and a 4K 120 Hz VRR television. The official dock supports up to 4K at 60 Hz or 1440p at 120 Hz; actual available VRR depends on SteamOS, dock firmware, cabling and the TV. DeckPilot reads advertised VRR capability but cannot enable VRR itself.

This release makes **future updates easy** and enables **optional, uncluttered Google Drive diagnostics** without a paid OpenAI API.

## One-time installation

1. Switch your Steam Deck into **Desktop Mode**.
2. Download **DeckPilot_TV_v0.6.0.zip** and extract it into a folder. Do not run the ZIP directly.
3. Open the extracted `deckpilot_tv_v0_6` folder in Dolphin; right-click the empty area and choose **Open Terminal Here**.
4. Enter `bash install.sh` and press Enter. No sudo, admin password, Steam password, or Decky needed.
5. Find **DeckPilot TV** in the application launcher and open it. Choose **Best Graphics**, **Best Performance** or **Balanced**.

The installer keeps your prior app files if upgrading from v0.5, and never removes your existing game preferences or game configuration backups.

## Updates — local ZIP today, GitHub after repository setup

To upgrade v0.5 to v0.6, download the accompanying **DeckPilot_TV_v0.6.0.zip** into `~/Downloads`. Open DeckPilot v0.5 and press Install v0.6.0. It should retain game preferences and backups.

v0.6 now supports public GitHub Releases as a feed **once a real repository has been set up**. In DeckPilot's Updates panel enter `owner/repo`, select Connect GitHub and Check online. The app checks automatically every six hours and downloads the latest compatible verified ZIP into its private update folder; it does **not** install without your approval. It accepts only a matching GitHub asset with a GitHub-issued SHA256 digest. The existing rollback feature remains. To prevent arbitrary download sources, the app supports only GitHub release APIs and GitHub-hosted assets. Trust the chosen repository; publisher signing is not separately implemented.

There is **no GitHub repository connected or published by this ZIP alone**. Creating a GitHub repo and publishing signed/trusted releases is a separate initial step. Until then, v0.6 still accepts new ZIPs saved in Downloads as before.

## Gaming Mode / Decky

The intended controller-first interface is a Decky Loader plugin. Source and a build workflow are available separately, but a compiled, tested Decky plugin is **not included** in this app ZIP. Decky plugin dependencies could not be downloaded in the build environment. After a repository exists, GitHub Actions can compile and publish it, and it can be installed from Decky without requiring Desktop Mode for mode selection. The core application continues to run in the background, preserving your per-game profiles.

## Optional Google Drive diagnostics — one visible file

The DeckPilot dashboard has a **Diagnostics and private Google Drive** section. After connecting Google Drive, the app can periodically replace the same file in the private folder:

`My Drive / DeckPilot Diagnostics / DeckPilot-Latest.zip`

It does not create dated copies or delete your other Drive documents. It checks about every 10 minutes, throttles uploads when reports are unchanged, and uses **only one fixed destination filename**. OAuth access is stored by rclone on your Steam Deck; DeckPilot never asks for a Google password. The configured rclone scope is `drive.file`, limiting access to items the connection creates.

**One-time setup:**

1. In Desktop Mode, open the application launcher and select **DeckPilot - Connect Drive**.
2. The helper downloads the official rclone binary (into your home folder if needed) and attempts to open your browser for Google authorisation.
3. Finish Google's approval screens. Never share OAuth tokens with ChatGPT.
4. Open DeckPilot TV. In **Diagnostics and private Google Drive**, first export and review a report, then press **Enable Drive uploads**.
5. Once uploaded, you can ask ChatGPT to check the latest Drive report via your connected Google Drive account.

This connection has not been tested live on SteamOS. **Google's OAuth compatibility may require extra setup:** the official rclone documentation warns its shared Google client ID is being retired during 2026. If the one-click connection fails, see [rclone's Google Drive guide](https://rclone.org/drive/) for creating a separate free OAuth client, or export a report locally. No extra OpenAI charges are needed. ChatGPT does **not** automatically receive a message, proactively inspect the logs or publish fixes merely because a file appeared in Drive.

**Privacy:** log redaction is best-effort, not guaranteed. Review the local ZIP before enabling automatic Drive uploads. Reports exclude raw game configuration files and Steam manifest paths; app log lines may still include sensitive details. Drive upload remains OFF by default.

## What the game optimiser actually does

- Detects installed Steam games in the default library and additional library folders detected through Steam's `libraryfolders.vdf`.
- Applies one of three broad presets to **existing compatible Unreal Engine `GameUserSettings.ini` files in Proton prefixes**. Other games appear in the library but are not changed.
- Graphics starts around 1080p/High, Balanced around 900p/Medium and Performance around 720p/Low for supported UE configs. These are *provisional starting points*, not independently benchmarked optimal values.
- Never edits an apparently running game. Backs up original game config files before edits. Skips later manual edits unless the user forces a per-game selection.
- Reads existing properly attributed MangoHud CSV logs for observed FPS, but does not install/enable MangoHud logging or perform universal benchmarking.
- Leaves TV display mode, VRR switching, Gamescope scaling, SteamOS TDP/FPS controls, Steam launch options and unsupported in-game menus untouched.

For a game-specific problem, see the dashboard's **Safety and restore** section. Existing profiles and backups remain after updating DeckPilot.

## Test / diagnostics

Inside the extracted folder:

```bash
python3 -m unittest discover -v
bash -n install.sh setup_drive.sh uninstall.sh
```

App diagnostics after installing:

```bash
python3 ~/.local/share/deckpilot-tv/app/deckpilot.py diagnose
python3 ~/.local/share/deckpilot-tv/app/deckpilot.py cloud-status
python3 ~/.local/share/deckpilot-tv/app/deckpilot.py update-status
```

Uninstall shortcut and service by running `bash uninstall.sh` from the extracted folder; saved game settings, backups, the Google remote and Drive files are not deleted.
