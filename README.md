# DeckPilot TV v0.6 — GitHub repository source

This is the app source + **Decky plugin development source** + a GitHub Actions build-and-release workflow.

You must first create a GitHub repository, push these files to it, and publish a `v0.6.0` tag. The workflow will run Python tests, build the Decky frontend using npm, package the app and plugin ZIPs, and attach both to the GitHub release. GitHub's release API supplies the SHA256 digest that DeckPilot uses for verification before downloading. Installation remains manual/approved and keeps rollback.

**Neither the GitHub repo nor a release has been created by producing this ZIP.** No compiled Decky bundle is included, and the plugin is untested on hardware. The initial `DeckPilot_TV_v0.6.0.zip` supplied separately is currently the easiest app upgrade from v0.5.

Codex GitHub connection test successful.
