# Slideshow control panel plan

Date: 2026-09-11  
Base: local `main` at `5872dc4`  
Branch: `feature/slideshow-control-panel`  
Status: proposed; this change creates the plan only.

## Goal and scope

Build a simple browser control panel using FastAPI and Uvicorn that another device on the same Wi-Fi can access through the frame's IP address to change the running slideshow's `display_seconds`. The server and slideshow run on the frame; the browser runs on a separate phone, tablet, or computer. Keep the interface minimal and the code easy to extend with additional controls later. Manage display, control, and existing application dependencies together through uv, one `pyproject.toml`, one `uv.lock`, and one environment.

- Assume the frame and the other device are already connected to the same Wi-Fi, with device-to-device traffic allowed and the frame's control port reachable. No Wi-Fi discovery, setup, credentials, reconnection logic, or network-manager integration.
- The only editable setting is `display_seconds`, measured in positive whole seconds. Zero and negative values are invalid because each photo needs a nonzero display interval.
- Use a plain HTML form with browser-default styling, FastAPI `Form`, and `python-multipart`. No JavaScript, CSS, or frontend build pipeline.
- Preserve photo rendering, cache handling, cloud synchronization, and existing command entry points.
- Initial scope assumes a trusted local network, with no login or public hosting. Bind to configurable `CONTROL_HOST` and `CONTROL_PORT`, defaulting to `0.0.0.0:8000`; on the other device, access the page at `http://<frame-lan-ip>:8000`. `0.0.0.0` is the server's bind address; the browser URL must use the frame's actual Wi-Fi IP address. `localhost` on the other device refers to that device itself. Port 8080 remains available for existing Google authorization.
- Proposed simplicity choices: updates live in memory, apply starting with the next successfully displayed photo, and reset to configured `DISPLAY_SECONDS` when the process restarts. State this behavior on the page and in the README. Persistent settings can be added behind the settings interface later.

## Current implementation and required changes

`client/config.py` currently parses `DISPLAY_SECONDS` as a float. `client/slideshow.py` imports that value once, so changing configuration cannot update a running slideshow. `client/main.py` runs initial synchronization, starts a background sync thread, and runs Pygame on the main thread. The CLI has `run`, `slideshow`, and `sync` commands, with lazy imports that allow help without runtime configuration.

uv already manages the base packages and test tools. Pygame is an optional `display` extra, and the README also documents a separately provisioned board build retained with `--inexact`. The target unified installation must account for that hardware compatibility gap.

## HTML form and routes

The page contains a heading, the current duration, one labeled input, an Apply button, and a message directly below the form. Render the current value into the input on GET. Use `<form method="post" action="/settings">` so the browser submits directly to the frame that served the page. A text input with `inputmode="numeric"` allows a numeric keyboard on mobile while preserving invalid text for correction. Server-side validation handles all submissions, including empty input; browser validation is not the authority. No JavaScript, CSS, remote fonts, scripts, or other internet assets are required.

| Method and path | Behavior |
| --- | --- |
| `GET /` | Return HTML showing the current settings and form; never modify settings. |
| `POST /settings` | Receive `display_seconds` through FastAPI `Form`, validate it, and update the shared settings only when valid. On success, send a 303 redirect to `/`; the resulting GET shows the updated value. On invalid input, return the form as HTML with status 422 and an error below it. |

Receive the form field as optional text (`Form(default=None)`) and explicitly validate it before updating the program. Form values arrive as strings, so accept `"5"` and convert it to integer 5. Strip surrounding whitespace, require one or more ASCII digits (`[0-9]+`), safely convert to an integer, and require a value greater than zero. Accept leading zeros, such as `"005"`, as 5. Reject missing/empty input, letters, decimal notation including `"5.0"`, fractions, scientific notation, signs, zero, negative values, and text such as `"true"` or `"null"`. Do not round or truncate. Catch conversion failures, including excessively long digit strings, as invalid input. The shared settings service must also reject non-integer Python values, including booleans, so future callers cannot bypass validation. [FastAPI form handling](https://fastapi.tiangolo.com/tutorial/request-forms/)

For invalid input, redisplay the submitted text and show **"Enter a positive whole number of seconds, such as 5."** in a paragraph immediately below the form, associated with the input through `aria-describedby`. Keep the prior active duration visible and unchanged. Escape submitted text before inserting it into HTML. Handle form parsing/request-validation errors with an HTML error response as well; malformed bodies may return 400 and unsupported content types 415. Expected input errors must never produce an uncaught exception, a 500 response, a raw JSON error page, or stop the server/slideshow. After an error, the user can correct the value and submit again.

Use POST for updates and a 303 redirect after success so refreshing the resulting page does not resubmit an update. Repeating the same valid setting is harmless. Keep the form routes separate from the settings service so additional controls can be added later. No JSON API is needed for this version. [FastAPI HTML and redirect responses](https://fastapi.tiangolo.com/advanced/custom-response/)

For startup configuration, parse the environment's string representation separately as a positive integer: `DISPLAY_SECONDS=5` is valid, while `5.0`, `0.2`, zero, negative, missing, and nonnumeric values fail with a clear configuration error. `IDLE_SECONDS` and `SYNC_INTERVAL` retain their existing float behavior. Do not edit the user's local `.env` automatically.

## Runtime design

1. Add a small `RuntimeSettings` service initialized from validated configuration, with a lock protecting reads and updates. Return snapshots rather than exposing mutable internal state. Concurrent valid writes use last-completed-write semantics.
2. Pass the same service instance to the FastAPI application factory and slideshow. Application construction must not start Pygame, perform cloud authorization, or create worker threads.
3. Keep Pygame on the main thread. Run one Uvicorn server in a managed background thread using `uvicorn.Config` and `uvicorn.Server`. Use one process, with reload disabled, so form handlers and display share the same state. A separately launched Uvicorn process would not control this in-memory slideshow. [Uvicorn programmatic lifecycle](https://uvicorn.dev/#config-and-server-instances)
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
| `python-multipart` | Required by FastAPI `Form` for receiving HTML form submissions. |

Use the minimal FastAPI and Uvicorn packages without their `standard` extras. FastAPI supplies the web framework and Uvicorn serves it. [FastAPI server documentation](https://fastapi.tiangolo.com/deployment/manually/)

Resolve compatible versions during implementation and record exact direct pins in the repository's existing style. uv will lock the transitive closure, including Starlette, Pydantic, Pydantic Core, and any required typing/support packages; these do not need independent direct declarations unless application code imports them. The form uses explicit text-to-integer validation and needs no custom Pydantic model. Review the lockfile diff for the exact added transitive packages rather than inventing a version list during planning.

Existing packages to retain in the unified runtime dependencies:

- `google-api-python-client`, `google-auth[requests]`, and `google-auth-oauthlib` for cloud access.
- `pillow` and `pillow_heif` for images; preserve the current `pillow_heif==1.4.0` compatibility pin.
- `python-dotenv` and `typer` for configuration and commands.
- Move existing `pygame==2.6.1` from the `display` extra into the base runtime dependencies so the default installation includes display and control together.

Keep existing `pytest`, `httpx`, and `click` development requirements in the `dev` group. No new test package is needed: FastAPI's `TestClient` uses the existing HTTPX/pytest tooling. No Jinja2, database, WebSocket library, or JavaScript package manager is needed for this page. Use Python's standard library for threading, synchronization, and small HTML substitutions (`string.Template` with explicit `html.escape` for dynamic text). [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/)

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
      app.py                         # NEW: application factory and GET/POST form routes
      page.py                        # NEW: render HTML with escaped values and errors
      server.py                      # NEW: Uvicorn thread startup/readiness/shutdown
      templates/
        index.html                   # NEW: plain HTML form and error paragraph
  tests/
    test_settings.py                 # NEW: state and startup integer validation
    test_control.py                  # NEW: form submission, validation, and HTML errors
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
| `pyproject.toml` | Unified dependencies including `python-multipart`, register `client.control`, include `templates/index.html` as package data. |
| `uv.lock` | Regenerate with uv after metadata changes. |
| `README.md` | Installation, panel URL, form/error behavior, commands, timing/reset behavior, and connected-Wi-Fi assumption. |
| `tests/conftest.py` | Use an integer display duration, inject isolated settings, preserve offline/headless fixtures. |
| `tests/test_slideshow.py` | Verify live updates using a fake clock instead of fractional display durations. |
| `tests/test_runtime.py` | Cover integrated commands, shared state, startup order, and cleanup. |

Use package-relative resource loading for the HTML so it does not depend on the shell's working directory. Verify wheel/sdist inclusion because setuptools currently has explicit package lists and `include-package-data = false`; add an explicit package-data declaration. Keep configuration/data relocation outside this feature.

## Necessary test cases

| Area | Cases and expected results |
| --- | --- |
| Startup configuration | Accept positive integer strings, including 1; reject missing, blank, decimal, zero, negative, and nonnumeric display values with clear errors. Float idle/sync intervals still work. Validate control port range and reject malformed port configuration. |
| Settings state | Initialize from configuration, retrieve/update snapshots, preserve state on invalid updates, isolate separate instances, and support concurrent reads/writes without partial state. A new runtime resets to configured duration. |
| Form reads and writes | GET renders the current integer without mutation. POST accepts `"1"`, `"10"`, whitespace-trimmed integers, and leading zeros; updates state; returns a 303 redirect to `/`. Following the redirect displays the accepted value. Refresh performs GET without another update; setting the same value succeeds. |
| Invalid form input | Submit missing/empty/whitespace-only values, `"abc"`, `"5.0"`, `"1.5"`, `"1/2"`, `"1e3"`, `"+5"`, `"0"`, `"-1"`, `"true"`, `"null"`, and a digit string exceeding the integer conversion limit. Each returns HTML with status 422 and the error directly below the form, retaining submitted text and the prior active duration. |
| Recovery without crashing | After each invalid submission, GET and a subsequent valid POST still succeed and the slideshow continues at its previous duration until a valid update. Malformed forms, unsupported content types, and request-validation failures produce handled HTML errors, never status 500 or an uncaught exception. |
| Page delivery and escaping | GET `/` serves a labeled input, POST form, Apply button, and associated error paragraph with no JavaScript/CSS or external assets. HTML-like invalid input is escaped when redisplayed. Packaged HTML loads independently of the working directory; responses expose no configuration secrets. |
| Live display integration | Submit a valid form while a photo is showing; the current interval finishes at its original duration and the next successful photo uses the new duration. Cover increases, decreases, and rejected submissions with fake ticks and the actual shared settings instance. |
| Empty/invalid cache | An update during the waiting screen affects the first valid photo; missing/corrupt images are skipped; the panel remains usable. Existing supported formats, EXIF orientation, scaling, and photo order still pass. |
| Commands and isolation | `run` and `slideshow` each start exactly one panel sharing the display's settings; `run` retains initial/background sync order; `slideshow` never accesses Drive; `sync` starts no server. Help and no-argument invocation still avoid runtime imports/configuration. |
| Server lifecycle | Readiness success, occupied port, startup timeout, unexpected server exit, and cleanup after initial-sync/display errors. Escape, window close, and Ctrl+C request server shutdown; joins are bounded and normal exit leaves no panel thread running. |
| Dependency/package installation | Fresh unified uv sync succeeds; imports and CLI help work; lock metadata is consistent; built wheel/sdist includes the control package and HTML. Verify the target board separately. |

Keep automated tests offline and headless with temporary data, mocked Drive calls, FastAPI `TestClient`, SDL dummy drivers, and fake time. Mock lifecycle boundaries for deterministic failure tests; use the manual smoke check to verify actual Uvicorn socket behavior. Do not use real credentials, cloud calls, or real multi-second waits in unit tests.

Manual acceptance checks on the already-connected frame:

1. On a separate phone, tablet, or laptop connected to the same Wi-Fi, open `http://<frame-lan-ip>:8000` and confirm the configured value appears. Perform the browser checks below from that device; accessing the page only on the frame does not satisfy acceptance.
2. Change 5 to 10, then to 1; confirm visible intervals change starting with the next photo while synchronization continues.
3. Submit empty input, letters, `5.0`, a fraction, zero, and a negative value; confirm a readable error appears directly below the form, the entered text is preserved, and the active duration remains unchanged. Correct the input and verify the next submission succeeds while the slideshow keeps running.
4. Refresh the page to retrieve current runtime state; restart the application and confirm the configured startup value returns.
5. Use cache-only mode without cloud connectivity; verify the local page and cached slideshow still operate.
6. Exit normally and with Ctrl+C; confirm port 8000 is released and restarting works. Start with that port occupied and verify the clear startup error.
7. Verify actual visible output with the board's uv-managed graphics packages; a dummy-display pass alone is insufficient.

## Implementation sequence and completion criteria

1. Unify dependency metadata and resolve the lockfile in an isolated environment; investigate the board Pygame source if needed.
2. Add strict configuration parsing and the shared settings service, with focused validation tests.
3. Add the app factory, GET/POST form routes, and plain HTML page; verify integer validation, errors below the form, recovery, redirects, and package assets.
4. Add managed Uvicorn startup and integrate shared settings into both display workflows; verify lifecycle and per-photo timing.
5. Update existing tests and documentation, run the full offline suite and package checks, then complete the board/browser smoke checks.

The feature is complete when a browser on another device connected to the same Wi-Fi can reach the frame's IP address and change its running slideshow's positive integer display interval through a plain HTML form with no JavaScript or CSS, invalid input shows an error below the form without changing state or crashing the application, the lifecycle exits cleanly, and display/control/base Python packages install together reproducibly through uv. Record any pending hardware checks explicitly. This planning change does not install packages or implement the feature.
