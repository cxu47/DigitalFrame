# Slideshow control panel plan

Date: 2026-09-11  
Base: local `main` at `5872dc4`  
Branch: `feature/slideshow-control-panel`  
Status: proposed; this change creates the plan only.

## Goal and scope

Build a simple browser control panel using FastAPI and Uvicorn to change the running slideshow's `display_seconds`. Keep the interface minimal and the code easy to extend with additional controls later. Manage display, control, and existing application dependencies together through uv, one `pyproject.toml`, one `uv.lock`, and one environment.

- Assume the frame is already connected to Wi-Fi and the browser can reach its local network address. No Wi-Fi discovery, setup, credentials, reconnection logic, or network-manager integration.
- The only editable setting is `display_seconds`, measured in positive whole seconds. Zero and negative values are invalid because each photo needs a nonzero display interval.
- Use plain HTML, a little inline CSS, and browser JavaScript; no prescribed visual design or frontend build pipeline.
- Preserve photo rendering, cache handling, cloud synchronization, and existing command entry points.
- Initial scope assumes a trusted local network, with no login or public hosting. Bind to configurable `CONTROL_HOST` and `CONTROL_PORT`, defaulting to `0.0.0.0:8000`; access the page at `http://<frame-lan-ip>:8000`. Port 8080 remains available for existing Google authorization.
- Proposed simplicity choices: updates live in memory, apply starting with the next successfully displayed photo, and reset to configured `DISPLAY_SECONDS` when the process restarts. State this behavior on the page and in the README. Persistent settings can be added behind the settings interface later.

## Current implementation and required changes

`client/config.py` currently parses `DISPLAY_SECONDS` as a float. `client/slideshow.py` imports that value once, so changing configuration cannot update a running slideshow. `client/main.py` runs initial synchronization, starts a background sync thread, and runs Pygame on the main thread. The CLI has `run`, `slideshow`, and `sync` commands, with lazy imports that allow help without runtime configuration.

uv already manages the base packages and test tools. Pygame is an optional `display` extra, and the README also documents a separately provisioned board build retained with `--inexact`. The target unified installation must account for that hardware compatibility gap.

## Interface and API

The page contains a heading, a labeled number input (`min=1`, `step=1`), an Apply button, and a small success/error message. Load the current value on opening the page. Submit JSON with browser `fetch`; validate whole-second input without rounding or truncation. Disable submission while a request is pending and show success only after the server accepts it. On failure, retain the entered value and explain the error. No remote fonts, scripts, or other internet assets are required.

| Method and path | Behavior |
| --- | --- |
| `GET /` | Serve the control page. |
| `GET /api/settings` | Return the current settings, initially `{"display_seconds": 5}` when configured as 5. |
| `PATCH /api/settings` | Accept `{"display_seconds": 10}` and return the accepted settings with status 200. |

Use a Pydantic request model with strict integer validation and a greater-than-zero constraint. Reject floats (including `5.0`), numeric strings, booleans, null, missing values, unknown fields, and malformed JSON with status 422; rejected updates leave settings unchanged. Require JSON for updates. Keeping a settings resource and a separate settings service makes adding another explicitly validated field straightforward. [Pydantic strict validation](https://docs.pydantic.dev/latest/concepts/strict_mode/)

For startup configuration, parse the environment's string representation separately as a positive integer: `DISPLAY_SECONDS=5` is valid, while `5.0`, `0.2`, zero, negative, missing, and nonnumeric values fail with a clear configuration error. `IDLE_SECONDS` and `SYNC_INTERVAL` retain their existing float behavior. Do not edit the user's local `.env` automatically.

## Runtime design

1. Add a small `RuntimeSettings` service initialized from validated configuration, with a lock protecting reads and updates. Return snapshots rather than exposing mutable internal state. Concurrent valid writes use last-completed-write semantics.
2. Pass the same service instance to the FastAPI application factory and slideshow. Application construction must not start Pygame, perform cloud authorization, or create worker threads.
3. Keep Pygame on the main thread. Run one Uvicorn server in a managed background thread using `uvicorn.Config` and `uvicorn.Server`. Use one process, with reload disabled, so API and display share the same state. A separately launched Uvicorn process would not control this in-memory slideshow. [Uvicorn programmatic lifecycle](https://uvicorn.dev/#config-and-server-instances)
4. Integrate panel startup into `digitalframe run` and `digitalframe slideshow`, including their legacy module entry points. Keep `digitalframe sync` as a one-shot operation without a web server. A small shared runtime helper should own settings creation and panel cleanup without duplicating orchestration.
5. For `run`, retain initial sync before the recurring sync worker and slideshow. Start the panel before initial sync so the page can respond during authorization or a slow cloud request. For `slideshow`, start the panel and display without any cloud access. Log the configured listening address and explain how to use the device's actual LAN IP.
6. Wait for server readiness with a bounded startup timeout, and propagate port-bind/startup failures as clear command failures. If initial sync or display initialization raises, stop the panel in `finally`. Detect an unexpected server exit and request a clean display exit with a logged error rather than leaving a silently unavailable panel.
7. Snapshot `display_seconds` after each successful photo render and use that value for the entire photo interval. A change from 5 to 10 during a photo leaves its current interval intact; the next photo receives 10 seconds. Continue processing Escape/window-close events during waits and while the cache is empty.
8. On Escape, window close, Ctrl+C, or a runtime exception, request Uvicorn shutdown and join its thread with a bounded timeout. Preserve the existing sync worker behavior; redesigning cloud transport cancellation is outside this feature. Keep all Pygame calls on the main thread.

## Packages and uv unification

New direct runtime requirements:

| Package | Purpose |
| --- | --- |
| `fastapi` | HTTP routes, request validation integration, and page responses. |
| `uvicorn` | Run the FastAPI ASGI application alongside the display. |
| `pydantic` | Explicit direct dependency because application code imports its validation models and fields. |

Use the minimal FastAPI and Uvicorn packages without their `standard` extras. FastAPI supplies the web framework and Uvicorn serves it. [FastAPI server documentation](https://fastapi.tiangolo.com/deployment/manually/)

Resolve compatible versions during implementation and record exact direct pins in the repository's existing style. uv will lock the transitive closure, including Starlette, Pydantic Core, and any required typing/support packages; these do not need independent direct declarations unless application code imports them. Review the lockfile diff for the exact added transitive packages rather than inventing a version list during planning.

Existing packages to retain in the unified runtime dependencies:

- `google-api-python-client`, `google-auth[requests]`, and `google-auth-oauthlib` for cloud access.
- `pillow` and `pillow_heif` for images; preserve the current `pillow_heif==1.4.0` compatibility pin.
- `python-dotenv` and `typer` for configuration and commands.
- Move existing `pygame==2.6.1` from the `display` extra into the base runtime dependencies so the default installation includes display and control together.

Keep existing `pytest`, `httpx`, and `click` development requirements in the `dev` group. No new test package is needed: FastAPI's `TestClient` uses the existing HTTPX/pytest tooling. No Jinja2, python-multipart, database, WebSocket library, or JavaScript package manager is needed for this page. Threading and synchronization use Python's standard library. [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/)

Target workflow after implementation:

```bash
uv sync --locked --no-dev             # Complete runtime: base + display + control
uv run --no-sync digitalframe run
uv run --no-sync digitalframe slideshow  # Cache-only display + control

uv sync --locked                      # Runtime plus existing dev tools
uv run --no-sync python -m pytest -q
uv lock --check
```

Update README installation commands and the CLI's missing-Pygame message to remove the old `--extra display` requirement. Keep dependency metadata and the generated lockfile together; do not reintroduce a maintained `requirements.txt`. uv supports declaring alternate package sources in project metadata when required by the target platform. [uv dependency management](https://docs.astral.sh/uv/concepts/projects/dependencies/)

Before deployment, validate the unified install in a separate environment on the board. If the normal Pygame distribution cannot reproduce its working SDL integration, obtain or build a compatible wheel and declare a reproducible, platform-specific uv source with its build procedure and artifact hash. Do not replace the working board environment during this investigation. Unification is not complete on that board while it depends on an undeclared Pygame installation retained through `--inexact`. OS display drivers, SDL/native libraries, and device permissions remain system prerequisites; uv manages the Python packages.

## Planned file structure

```text
DigitalFrame/
  .plans/
    slideshow-control-panel.md       # This plan
  client/
    settings.py                      # NEW: validated shared runtime settings
    runtime.py                       # NEW: shared panel/display lifecycle helper
    control/
      __init__.py                    # NEW: control package
      app.py                         # NEW: application factory and settings routes
      schemas.py                     # NEW: request/response validation models
      server.py                      # NEW: Uvicorn thread startup/readiness/shutdown
      static/
        index.html                   # NEW: page with small inline CSS/JavaScript
  tests/
    test_settings.py                 # NEW: state and startup integer validation
    test_control.py                  # NEW: page and API behavior
    test_control_server.py           # NEW: server lifecycle failure handling
```

Modify these existing files during implementation:

| File | Planned change |
| --- | --- |
| `client/config.py` | Integer parsing for display duration; control host/port configuration. |
| `client/slideshow.py` | Read per-photo duration from shared settings; preserve rendering and standalone entry point. |
| `client/main.py` | Integrate the panel with the sync/display lifecycle. |
| `client/cli.py` | Route cache-only startup through the shared runtime; update help and dependency guidance. |
| `.env.example` | Document integer `DISPLAY_SECONDS`, `CONTROL_HOST`, and `CONTROL_PORT`. |
| `pyproject.toml` | Unified dependencies, register `client.control`, include `static/index.html` as package data. |
| `uv.lock` | Regenerate with uv after metadata changes. |
| `README.md` | Installation, panel URL, commands, timing/reset behavior, and connected-Wi-Fi assumption. |
| `tests/conftest.py` | Use an integer display duration, inject isolated settings, preserve offline/headless fixtures. |
| `tests/test_slideshow.py` | Verify live updates using a fake clock instead of fractional display durations. |
| `tests/test_runtime.py` | Cover integrated commands, shared state, startup order, and cleanup. |

Use package-relative resource loading for the HTML so it does not depend on the shell's working directory. Verify wheel/sdist inclusion because setuptools currently has explicit package lists and `include-package-data = false`; add an explicit package-data declaration. Keep configuration/data relocation outside this feature.

## Necessary test cases

| Area | Cases and expected results |
| --- | --- |
| Startup configuration | Accept positive integer strings, including 1; reject missing, blank, decimal, zero, negative, and nonnumeric display values with clear errors. Float idle/sync intervals still work. Validate control port range and reject malformed port configuration. |
| Settings state | Initialize from configuration, retrieve/update snapshots, preserve state on invalid updates, isolate separate instances, and support concurrent reads/writes without partial state. A new runtime resets to configured duration. |
| API reads and writes | GET returns the configured integer; PATCH returns and stores the accepted value; a later GET sees it; setting the same value succeeds. |
| Invalid API input | Reject fractional and integral floats, numeric strings, booleans, null, zero, negatives, missing field/body, arrays, unknown fields, malformed JSON, and non-JSON submissions. Confirm rejected requests never change the prior value. |
| Page delivery | GET `/` serves HTML with a labeled whole-seconds input and Apply action; packaged HTML can be loaded independently of the working directory. API responses expose only control settings, never configuration secrets. |
| Live display integration | Submit an API update while a photo is showing; the current interval finishes at its original duration and the next successful photo uses the new duration. Cover both increases and decreases with fake ticks and the actual shared settings instance. |
| Empty/invalid cache | An update during the waiting screen affects the first valid photo; missing/corrupt images are skipped; the panel remains usable. Existing supported formats, EXIF orientation, scaling, and photo order still pass. |
| Commands and isolation | `run` and `slideshow` each start exactly one panel sharing the display's settings; `run` retains initial/background sync order; `slideshow` never accesses Drive; `sync` starts no server. Help and no-argument invocation still avoid runtime imports/configuration. |
| Server lifecycle | Readiness success, occupied port, startup timeout, unexpected server exit, and cleanup after initial-sync/display errors. Escape, window close, and Ctrl+C request server shutdown; joins are bounded and normal exit leaves no panel thread running. |
| Dependency/package installation | Fresh unified uv sync succeeds; imports and CLI help work; lock metadata is consistent; built wheel/sdist includes the control package and HTML. Verify the target board separately. |

Keep automated tests offline and headless with temporary data, mocked Drive calls, FastAPI `TestClient`, SDL dummy drivers, and fake time. Mock lifecycle boundaries for deterministic failure tests; use the manual smoke check to verify actual Uvicorn socket behavior. Do not use real credentials, cloud calls, or real multi-second waits in unit tests.

Manual acceptance checks on the already-connected frame:

1. Open the page from a phone/laptop on the same Wi-Fi and confirm the configured value appears.
2. Change 5 to 10, then to 1; confirm visible intervals change starting with the next photo while synchronization continues.
3. Check empty/decimal/zero input, a failed request, and successful retry; verify feedback is readable on a phone.
4. Refresh the page to retrieve current runtime state; restart the application and confirm the configured startup value returns.
5. Use cache-only mode without cloud connectivity; verify the local page and cached slideshow still operate.
6. Exit normally and with Ctrl+C; confirm port 8000 is released and restarting works. Start with that port occupied and verify the clear startup error.
7. Verify actual visible output with the board's uv-managed graphics packages; a dummy-display pass alone is insufficient.

## Implementation sequence and completion criteria

1. Unify dependency metadata and resolve the lockfile in an isolated environment; investigate the board Pygame source if needed.
2. Add strict configuration parsing and the shared settings service, with focused validation tests.
3. Add the app factory, API, and simple page; verify request behavior and package assets.
4. Add managed Uvicorn startup and integrate shared settings into both display workflows; verify lifecycle and per-photo timing.
5. Update existing tests and documentation, run the full offline suite and package checks, then complete the board/browser smoke checks.

The feature is complete when a browser on the existing Wi-Fi can change a running slideshow's positive integer display interval, invalid updates cannot corrupt state, the lifecycle exits cleanly, and display/control/base Python packages install together reproducibly through uv. Record any pending hardware checks explicitly. This planning change does not install packages or implement the feature.
