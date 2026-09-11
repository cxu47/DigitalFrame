# uv, native deployment, and CLI refactoring plan

Date: 2026-09-10  
Reviewed baseline: `c3bedda` on `feature/repository-cleanup-and-display-history`  
Status: implemented on the existing `feature/repository-cleanup-and-display-history` branch; local validation passed. Physical-board migration and live Drive validation remain pending.

## Intended outcome

Run DigitalFrame as one Linux user with a looping slideshow and background photo synchronization. Make installation on another machine repeatable through uv, while retaining the working board's graphics setup. Leave a straightforward path for a future local control server handling Wi-Fi setup and slideshow settings.

Recommended direction: native deployment with uv, a small CLI, and the existing `client/` package. Remove Docker after validating the native replacement. A CLI is useful with either deployment model; it does not depend on keeping Docker.

Keep existing tests outside this work: do not inspect, execute, repair, or reorganize them. Preserve the historical display archive, local `.env`, credentials, tokens, cached photos, and demo asset. Retain the user's Drive folder ID in `.env.example` and the `INFO` logging default. This refactor does not add the control server, Wi-Fi provisioning, cache reconciliation, or new slideshow features.

## 1. Deployment decision

| Option | Fit for this project | Decision |
| --- | --- | --- |
| Native Python environment managed by uv | Fits one user running the display process and accessing host networking; simplifies the normal install/run workflow. | Primary deployment. |
| Docker | Adds an image/runtime workflow plus host display/device/session configuration. The current image has not been verified on the physical board. | Remove the active Dockerfile and setup instructions after the native workflow is verified. Git history preserves the earlier configuration. |
| Future local control server | Can run natively alongside the slideshow and use the same project environment. Its existence alone does not require containers. | Design later around the actual controls needed. |

uv addresses Python dependency installation and locking, not the entire machine image. A committed lockfile records resolved Python dependencies across platforms, but successful installation and display operation still depend on available artifacts and the host environment. [uv project guide](https://docs.astral.sh/uv/guides/projects/)

- [x] Document OS prerequisites separately: a compatible Python interpreter, SDL/image libraries where needed, display drivers, the intended graphical/TTY session, and device permissions.
- [x] Define transfer as checking out the same repository revision, installing prerequisites, restoring local configuration/credentials, and syncing the lockfile on the target. Do not copy the laptop's `.venv` to a Pi.
- [x] Keep deployment under the intended user. For eventual automatic startup, use a service/session arrangement appropriate to that board and call the installed CLI directly. Do not add a generic startup service until display-session behavior is verified.
- [x] Treat Wi-Fi changes as an interface to the host's network manager, with whatever narrowly scoped authorization the chosen OS requires. Package installation does not configure that access.

## 2. Replace manual package management with a uv project

- [x] Add `pyproject.toml` for project metadata, Python compatibility, direct dependencies, development tooling, packaging, and the CLI entry point. Generate `uv.lock` for version control; never edit the lockfile manually.
- [x] Initially target Python `>=3.12,<3.15`, reflecting the current local 3.12 and archived board 3.14 environments. Treat this as a proposed compatibility range to verify, not a claim that all versions/platforms have been tested. Avoid a repository-wide `.python-version` that silently replaces the board's working interpreter.
- [x] On the board, select its existing interpreter explicitly and disable automatic Python downloads. Check uv's own platform support separately from Python and graphics-wheel availability. [Python selection](https://docs.astral.sh/uv/concepts/python-versions/), [uv platform support](https://docs.astral.sh/uv/reference/policies/platforms/)
- [x] Declare the current direct runtime dependencies: `google-api-python-client`, `google-auth[requests]`, `google-auth-oauthlib`, `pillow`, `pillow_heif`, and `python-dotenv`. Handle Pygame using the display profiles below. Verify the list against active imports during implementation.
- [x] Seed the initial resolution with the existing pins as migration constraints, then review the resulting lockfile before removing temporary constraints. Keep `pillow_heif==1.4.0` and the current direct-package versions initially; do not combine migration with a general upgrade. Transitive packages belong in the lockfile rather than a copied list of application dependencies. [uv migration guidance](https://docs.astral.sh/uv/guides/migration/pip-to-project/)
- [x] Move existing pytest and retained HTTP/CLI tooling into a `dev` dependency group, preserving its pins without inspecting or changing tests. Record any unavoidable resolution changes. Runtime installation will exclude this group. [Dependency groups](https://docs.astral.sh/uv/concepts/projects/dependencies/)
- [x] Remove the hand-maintained `requirements.txt` once the uv workflow works. No current non-uv consumer has been identified beyond the Dockerfile being retired. If a concrete consumer remains, generate its requirements from `uv.lock` with `uv export` and document the selected dependency profile; never maintain two independent dependency lists.
- [x] Update `.gitignore` only for generated packaging artifacts as needed. Commit `pyproject.toml` and `uv.lock`; keep `.venv`, build output, private local files, and machine-specific wheels untracked.

### Preserve the board's Pygame/SDL build

The existing archive records Pygame 2.6.1 inside the board's virtual environment and system SDL libraries, but does not preserve the build command. The migration must account for this explicitly.

Use two documented installation profiles initially:

| Profile | Dependency approach | Intended use |
| --- | --- | --- |
| Standard display | An explicit `display` extra containing `pygame==2.6.1`, installed from the resolved source after platform verification. | Fresh installations with a working compatible wheel/build. |
| Existing board display | Base project dependencies plus the separately provisioned, known-working Pygame build. Do not enable the `display` extra for this profile. | Preserve the archived board's graphics behavior while its build provenance is recovered. |

The display extra is optional only as a provisioning choice; the slideshow still requires Pygame. Both profiles must provide it before running the frame. The CLI should explain a missing Pygame installation when a display command is requested, while allowing help and sync-only commands to work.

- [x] First verify migration in a separate checkout/environment. Do not run exact synchronization over the working board environment as an experiment.
- [x] For the existing-board profile, use locked, inexact synchronization to retain its separately installed Pygame. Do not enable the registry display extra or use an all-extras command there. `uv sync` normally removes undeclared packages, while `--inexact` retains extras unless they conflict with declared requirements. [Sync behavior](https://docs.astral.sh/uv/concepts/projects/sync/)
- [x] Document the board build's interpreter ABI, Pygame version, linked SDL libraries, and installation procedure/artifact hash when available. A future reproducible custom source can use uv's platform-specific sources. Until then, label this profile as an explicit reproducibility exception; the lockfile alone cannot recreate that Pygame build. [Dependency sources](https://docs.astral.sh/uv/concepts/projects/dependencies/)
- [x] Do not assume `--system-site-packages` reproduces the archived setup: the recorded Pygame package was inside `.venv`. Determine whether a new board uses a system package, custom wheel, or source build before prescribing a command.

Proposed commands, to validate before publishing in the README:

```bash
# Fresh standard display installation, from the repository root:
uv sync --locked --no-dev --extra display
uv run --no-sync digitalframe run

# Existing board profile, after selecting its actual interpreter path:
uv sync --locked --no-dev --inexact --python /path/to/board/python --no-python-downloads
uv run --no-sync digitalframe run
```

The second sequence requires Pygame to have already been provisioned in that environment. `--no-sync` deliberately separates runtime startup from dependency changes; installation/update is an explicit maintenance step. An eventual startup service should use the absolute path to `.venv/bin/digitalframe run` so restarting the frame does not invoke a package resolver. [uv locking and execution controls](https://docs.astral.sh/uv/concepts/projects/sync/)

## 3. Add a small CLI and preserve the current package layout

Use standard-library `argparse`; this interface does not need another CLI dependency. Package the existing `client/` directory with `setuptools.build_meta` and explicit package selection for `client` and `client.storage`. Add `client/storage/__init__.py` so both packages are explicit. Exclude cache, secrets, logs, tests, and the demo from build artifacts.

Define `[project.scripts]` with `digitalframe = "client.cli:main"`. Console entry points require an installed project/build configuration. Verify editable checkout installation; independently distributed wheels and relocatable data directories are not goals of this migration. [uv entry points and packaging](https://docs.astral.sh/uv/concepts/projects/config/)

| Command | Behavior |
| --- | --- |
| `digitalframe run` | Current full workflow: initial sync, background synchronization, then the slideshow. |
| `digitalframe slideshow` | Display the configured local cache without contacting Google Drive. |
| `digitalframe sync` | Synchronize once and exit, without importing or initializing the display stack. |
| `digitalframe --help` | Show usage without reading required configuration, opening credentials, or importing Pygame. |

- [x] Add `client/cli.py` for argument parsing and dispatch only. Use lazy imports after parsing so help and sync-only operation do not depend on display availability. No arguments should show help rather than unexpectedly starting OAuth or a window.
- [x] Add `client/__main__.py` as a thin delegate, enabling `python -m client` with the same subcommands.
- [x] Retain `client/main.py` as the application startup coordinator. Keep existing module entry points (`python -m client.main`, `python -m client.slideshow`, and `python -m client.sync`) working through the same underlying functions.
- [x] Keep configuration values, `.env` loading/precedence, relative paths under `client/`, absolute-path support, OAuth port/browser behavior, `INFO` logging, and the user's example folder ID unchanged. Document repository-root execution so existing path assumptions remain explicit.
- [x] Keep rendering on the main thread and preserve current sync ordering, intervals, sorted playback, image formats, EXIF correction, memory-conscious resizing, cache identity, and `.part` handling.
- [x] Avoid creating `src/`, renaming `client/`, moving runtime data, or splitting into multiple projects just to introduce a CLI. Any later standalone package/data-path migration should be its own plan.

Proposed layout changes only:

```text
DigitalFrame/
  pyproject.toml                  # new: metadata, dependencies, groups, entry point
  uv.lock                         # new: generated lockfile
  MANIFEST.in                     # new: exclude local data/history from source distributions
  README.md                       # revised install/run/deployment guidance
  .gitignore                      # packaging output exclusions, if needed
  client/
    __main__.py                   # new: module entry point
    cli.py                        # new: argument parsing and command dispatch
    main.py                       # existing application coordinator
    config.py                     # existing configuration and path semantics
    slideshow.py                  # existing display implementation
    sync.py                       # existing synchronization
    logging_config.py             # existing logging
    storage/
      __init__.py                 # new: explicit storage package
      google_drive.py             # existing provider implementation
```

`client/__init__.py`, cache/secrets folders, `assets/`, `logs/`, `tests/`, and `.plans/` remain in place. The intended removals are `Dockerfile` and the hand-maintained `requirements.txt`, subject to the native verification and consumer check above.

## 4. Leave a clear boundary for future local controls

The future server should call application/configuration functions rather than shelling out to the CLI or starting a second slideshow. Keep CLI parsing separate from application behavior now; add the server adapter only when implementing those controls.

- Slideshow settings will eventually need validated runtime configuration, persistence, and explicit reload behavior. Current import-time constants are sufficient for this migration; replacing them with a settings object belongs with the actual settings feature.
- Wi-Fi setup should use the chosen OS network manager through a small dedicated adapter. Decide local-only versus LAN browser access when that feature is scoped; neither requires a server framework dependency today.
- Keep one owner for the display loop. Decide server thread/process integration and graceful lifecycle management when the HTTP server is introduced, preserving Pygame's main-thread requirements.
- Do not add a web framework, API skeleton, database, message broker, privileged launcher, or container stack speculatively.

## 5. README and historical documentation

- [x] Preserve the README's current section order, motivation, demo, and historical milestones. Add compact setup/run subsections within “Project Status” if needed to distinguish the standard and existing-board profiles.
- [x] Replace pip/venv setup instructions with verified uv installation, interpreter selection, locked synchronization, and CLI commands. Explain runtime versus development dependencies and how deliberate dependency updates change `uv.lock`.
- [x] Explain how to set up a new machine, including OS/display prerequisites, `.env`, credentials/token placement, cache directories, and the difference between package installation and display-device configuration.
- [x] Remove active Docker build/mount instructions when Docker is retired. Retain Phase 1's historical Docker milestone and add a short explanation of the current native deployment decision.
- [x] Keep links to `logs/README.md`. Historical captures/scripts and the previous cleanup plan remain historical records; do not rewrite them to look as though uv was used originally. Add a current-workflow note to the archive index only if needed.

## 6. Implementation order and acceptance

1. Continue from cleanup revision `c3bedda` on the current feature branch, as explicitly requested by the user. Inventory dependency pins, entry points, interpreter versions, and the known-working board display setup. Preserve unrelated work.
2. Add project metadata and generate the lockfile in an isolated environment. Check the dependency diff, development-group separation, package contents, and both display profiles before touching the deployed environment.
3. Implement the small CLI and package entry points, keeping existing invocation paths functional.
4. Verify the native installation and commands, then remove Docker and the manual requirements file and update the README in the same change.
5. Record exact local and board verification results in this plan. If board access is unavailable, explicitly leave that acceptance item pending and preserve the working deployment until it can be checked.

Acceptance checklist:

- [x] A fresh standard-profile install succeeds from the committed lockfile; repeated locked sync does not change it, and runtime installation excludes development tooling.
- [ ] Existing-board migration retains the selected interpreter and Pygame/SDL build; an actual connected display still shows the slideshow. Record board/OS/ABI and physical observations separately from headless checks.
- [x] Package inspection shows only intended Python package files, with no cache, secrets, or historical captures bundled.
- [x] CLI help works without `.env` or Pygame; sync works without a display; cache-only slideshow does not initiate OAuth. Existing module entry points retain their behavior.
- [x] Focused manual smoke checks cover normal startup, waiting screen, supported images/EXIF/HEIC, invalid/missing images, exit handling, and temporary-cache synchronization. Do not inspect or run the existing tests.
- [x] Local `.env`, credentials, tokens, user photos, example Drive folder ID, `INFO` default, and historical files remain intact.
- [x] README commands match the implemented profiles; OS-specific and custom-build limitations are stated accurately. The repository has one authoritative dependency workflow and no active Docker references outside intentional history.

Completion means the uv-managed native workflow is usable, the CLI is a small wrapper around preserved behavior, documentation matches the delivered setup, and any missing physical-board evidence is recorded without claiming full deployment verification.


## Implementation record — 2026-09-10

Implemented on `feature/repository-cleanup-and-display-history` at the user's request; no new branch was created. The application configuration, synchronization, rendering, logging, and Google Drive modules remain unchanged. New CLI modules call the existing functions and preserve all legacy module entry points.

### Delivered changes

- Added `pyproject.toml` with six direct runtime dependencies, a `display` extra, a separate `dev` group for existing tooling, explicit packaging of `client` and `client.storage`, and the `digitalframe` console command. Python compatibility is declared as `>=3.12,<3.15`; only Python 3.12.3 was exercised locally.
- Generated `uv.lock` with uv 0.12.13, using temporary constraints from the old requirements file. Removed those constraints after seeding the lock. All 37 original package pins remain in the generated lockfile. Additional entries are DigitalFrame itself, Pygame 2.6.1, and Colorama for platform-specific dependencies. The new build backend is pinned separately to setuptools 84.0.0.
- Added `client/cli.py`, `client/__main__.py`, and `client/storage/__init__.py`. Commands are `run`, `slideshow`, and `sync`; no arguments show help. Display commands explain a missing Pygame installation. Lazy imports keep help free of configuration/dependency initialization and sync free of display imports.
- Added `MANIFEST.in` beyond the initially listed files because excluding package data from wheels alone does not cover source distributions. Both formats explicitly exclude local data, existing tests, and historical files. Updated `.gitignore` for packaging output and local wheel artifacts.
- Removed `Dockerfile` and `requirements.txt` after the native installation and CLI checks passed. No other active consumer of the requirements file was found outside intentional historical documentation. README installation, operation, update/export, and deployment guidance now uses uv; the previous headings and historical Docker milestone remain.
- Preserved `.env.example`, including the user's Drive folder ID and `INFO` default, as well as local configuration, secrets, photos, and all archive files. Historical documentation was not rewritten.

### Verification results

- Fresh standard-display and base-profile environments installed successfully in isolated checkouts on Linux AArch64/Python 3.12.3. The runtime environments excluded pytest, HTTP development tooling, and CLI development tooling. `uv pip check` passed for the standard environment.
- Repeating a locked standard-profile sync left the lockfile unchanged. A subsequent inexact base-profile sync retained the interpreter and every checked Pygame native-library/metadata hash. This validates the preservation mechanism locally, not the physical ARMv7 board.
- CLI help, no-argument help, subcommand help, invalid-command status, and missing-Pygame guidance passed without `.env` or Pygame in the base environment. Sync dispatch passed with synthetic remote data and a temporary cache while Pygame imports were explicitly blocked.
- The cache-only CLI slideshow displayed/exited with a dummy SDL backend without loading the Google Drive module. The full CLI workflow performed initial synchronization, started the existing background thread, and displayed/exited using temporary data and a simulated remote listing.
- Focused temporary smoke checks passed for JPEG/EXIF orientation, PNG scaling/letterboxing, HEIC rendering, waiting-screen/empty-cache exit, invalid/missing images, event handling, sorted filtering, filename skipping/duplicates, `.part` completion/cleanup, and listing failures.
- `uv build` successfully built a source distribution and wheel. Inspection confirmed all intended Python modules and excluded synthetic sentinels representing cache, secrets, `.env`, tests, assets, logs, and plans. The existing test suite was not inspected, executed, or modified.
- `uv lock --check`, all-pin comparison, and a runtime-only requirements export passed. Exported dependencies included Pygame and excluded development packages. The export remains a temporary compatibility artifact, not a second tracked requirements file.
- Applied the verified inexact profile to the local workspace environment so `.venv/bin/digitalframe` is available. This brings its previously installed pillow_heif 1.5.0 back to the repository's retained 1.4.0 pin and preserves its Pygame build and existing development tooling. uv itself was installed in a temporary tools environment; the README documents installation for other machines.

### Remaining deployment checks

- [ ] On the actual ARMv7 board, verify uv/interpreter availability, provision or preserve its custom Pygame/SDL build, and record the missing original build procedure/artifact provenance where recoverable.
- [ ] Confirm physical display visibility, continued slideshow operation, and restart/session behavior on the target machine. Headless AArch64 checks do not establish this.
- [ ] Exercise live Google OAuth/token refresh and remote synchronization with temporary cache data on the deployment. Local validation used synthetic remote data and did not access private credentials.

No control server, Wi-Fi integration, auto-start service, current-test-suite refactor, or standalone wheel deployment was added. These remain separate work.
