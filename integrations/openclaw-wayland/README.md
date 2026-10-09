# OpenClaw on this Wayland desktop

OpenClaw runs locally as the `openclaw-gateway` user service on
`127.0.0.1:18789`. Its model is `ollama/qwen3.5:4b` from Local Coder's private
Ollama service on `127.0.0.1:11435`. No messaging channel or remote Gateway
listener was configured. Launch the signed-in dashboard with:

```bash
/home/gerald/.openclaw/bin/openclaw dashboard
```

The bundled OpenClaw `cua-computer` provider cannot capture this Hyprland
Wayland session; it fails at X11 `GetImage`. It is disabled. This plugin instead
adds four direct agent tools:

- `wayland_screenshot`: captures the focused monitor, or a named monitor, with
  `grim` and returns an image and a one-use frame ID.
- `wayland_click`: moves the pointer with Hyprland's Lua dispatcher, then sends
  a local mouse button through `/dev/uinput`.
- `wayland_type`: enters text through the Wayland clipboard and the app's paste
  shortcut. This replaces the current text clipboard.
- `wayland_key`: sends a supported navigation key through `/dev/uinput`.

Clicks, typing, and keys require a frame ID from a recent screenshot. The
bridge checks the monitor geometry again before input and invalidates the frame
after each action. It cannot tell whether an app changed its contents since the
screenshot, so the agent should capture a new image after each action.

## Maintain or stop

To stop OpenClaw immediately:

```bash
systemctl --user stop openclaw-gateway
```

To revoke the desktop tools while leaving OpenClaw running:

```bash
/home/gerald/.openclaw/bin/openclaw plugins disable local-wayland
```

OpenClaw's `full` tool profile also permits shell commands, so stopping this
plugin alone does not remove all host access. The Gateway is loopback-only and
uses a local token. Keep its token private. The 4B local model can use the tools,
but review consequential actions because small models can misread screens or
instructions.

## Rebuild

This plugin needs Node 24.16+ or 26.1+, a C compiler, `grim`, `hyprctl`,
`wl-copy`, and user access to `/dev/uinput`. From this directory:

```bash
PATH=/home/gerald/.openclaw/tools/node/bin:$PATH npm ci
PATH=/home/gerald/.openclaw/tools/node/bin:$PATH npm run plugin:build
PATH=/home/gerald/.openclaw/tools/node/bin:$PATH npm run plugin:validate
/home/gerald/.openclaw/bin/openclaw plugins reload local-wayland --wait --accept-capabilities
```

The plugin is installed with `--link`, so OpenClaw loads this checkout's built
files. The compiled `wayland-input` helper stays beside `dist/` and is ignored
by Git; rebuild it after cloning this project.

## Verified here

- The Gateway returned a completion from the private Ollama service.
- OpenClaw's managed Chrome profile started successfully.
- The plugin returned a 1920x1080 desktop image through the Gateway tool API.
- The plugin pasted text and pressed Enter into a temporary Wayland terminal;
  the terminal wrote the exact expected text to a proof file.
- The plugin clicked Confirm in a temporary dialog; it exited successfully.
- An OpenClaw agent turn called `wayland_screenshot` and reported the monitor
  and dimensions.
