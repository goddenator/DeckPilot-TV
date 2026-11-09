# DeckPilot TV — Decky Loader plugin source

**NOT an installable Decky ZIP yet.** This is a development source release. `dist/index.js` must be built from `src/index.tsx` before creating a Decky plugin ZIP. The ChatGPT build environment could not access npm; no device or real Decky runtime test has taken place. Do not try to install the source ZIP through Decky.

This plugin uses the documented Decky React/Python bridge, and connects to the locally installed DeckPilot TV user-space application (v0.6+). No root access is requested by the plugin.

On a Linux development environment with Node and npm access:

```
cd decky
npm install
npm run build
```

Confirm `dist/index.js` was generated. Package `DeckPilot/` containing `dist/index.js`, `plugin.json`, `package.json`, `main.py` and `LICENSE` into a ZIP. Install through Decky → Settings → Developer → Install Plugin from ZIP. This is an experimental third-party plugin and is not listed in the Decky Store.
