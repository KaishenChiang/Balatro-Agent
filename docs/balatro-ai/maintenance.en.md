# Installation, maintenance and recovery

The transport hardening is identified by health.transport_policy="bounded-query-retry-v1" after the Python service is reloaded. Lock waits, response streaming and bounded retries of read-only queries share one deadline; act_submit is never retried. Transient approval-network failures retain the task and original record under [network recovery](network-recovery.md). Only an explicit host non-execution approval-timeout receipt permits one identical client retry after original-ID and unchanged-state checks. Keep approval and genuine UNKNOWN safeguards. If the client has no MCP reload control, the user may restart Codex after saving the checkpoint and keeping the game window. The separate rendered-side readiness Mod patch requires normal closed-game, idle, backup and hash checks before installation; source changes and isolated tests do not prove it is installed or tested live.

Use the complete project folder on Windows x64 with a legitimate Steam installation of Balatro. Run **Balatro Agent.exe** from that folder. Python, uv, locked dependencies and fixed Mod archives are bundled; do not download an EXE alone or move it out of the folder. Keep the folder in a permanent writable location.

The interface follows the Windows display language (Chinese or English fallback) and also offers `Language / 语言`. Changing this selector changes labels and both prompt paths, preserves your deck/stake selection and does not restart preparation. It does not change Balatro's language or select a game profile. The optional launcher argument `--language en` or `--language zh-CN` chooses an interface language for that launch.

Before installation or updates, close Balatro normally and resolve pending actions. The preparation worker discovers a unique Steam installation, verifies bundled hashes, freezes the installation plan, checks backups and existing Mods, builds the adapter and configures MCP. It preserves unrelated settings, Mods, profiles and saves. A conflict is reported rather than silently replaced. A partial failure retains its real receipts; this is not a cross-file atomic rollback guarantee.

When ready, use **Start in Codex**, review the prefilled prompt and send it. A successfully dispatched project-link request closes the launcher. **Copy play prompt** includes the actual project path and full rules; paste it in a local Codex chat with the MCP tools loaded. Copy and fallback paths keep the launcher open. After copying you may close it manually. Codex manages the MCP process independently. Keep the project folder.

If a chat lacks the tools, reload MCP with the client's available controls or reopen Codex. Preparation does not prove an existing chat has reloaded. The path in a prompt does not change that chat's working directory or permissions. The interface shows a short localized failure explanation; **Details** retains real worker output and paths for troubleshooting.

## Moving or updating the project

Verified installation receipts and mirrored unresolved-action records under the client configuration directory permit repairing a moved or re-downloaded project's registered path. The launcher checks ownership, installed hashes, normal game closure and idle old/new checkpoints, then backs up and updates only the managed entry. A known 11-tool registration can upgrade to the current 12 tools. Other/custom configuration conflicts stop for inspection. Missing trusted receipts cannot be bypassed by guessing an old path.

Back up and migrate `runs/local-experience/` separately. Both source and local experience keep one `current.md` per topic. Local content takes priority; an update supplies the full amended content and atomically replaces that same file. Compact write receipts and update counters support conflict checks and deduplication without retaining full old documents. The public baseline never replaces an amended local topic. Use `scripts/project.py experience-single` to preview a verified one-time legacy archive/migration, then add `--apply` to execute it. Reload the MCP service and check `notes_storage_format="single-current-v2"` before writing. Preserve `runs/live/` (including `run-plans/`), checkpoints, UNKNOWN records, installation ledgers and backups during maintenance. A changed session or language does not justify deleting records, locks or saves to bypass an unresolved action.

With explicit authorization to integrate local experience into source, preview `scripts/project.py experience-promote`, then add `--apply`. It verifies a backup and replaces the matching source current files with the validated local current files, leaving local files intact. Independently changed source topics that conflict with local content stop for review. This command never publishes or pushes automatically.

Chinese `current.md` guides contain strategy only. Default MCP `strategy` reads omit provenance, historical facts and save receipts; explicit `content`/`full` reads expose those audit fields when revising or investigating a note. Each store keeps its audit metadata under `.metadata/experience/`. Back up and migrate the entire experience root, including metadata, to retain validation and deduplication.

For a stopped/unresolved action, query its original ID and observe through MCP. Never replay an uncertain action or promote UNKNOWN to a loss. `recover_lost_session` is only for a confirmed lost old session under its contract. Normal wins/losses retain the game results window; closing the game requires a separate explicit request.

If the local pending record is absent, retirement still requires the service's own durably delivered missing-record status from one verified old session, matching registration, independent checkpoints, current profile and fresh observation. Known submission history or ambiguous sessions block this path. RETIRED preserves the original UNKNOWN outcome; it never proves the action was unsubmitted, successful or a normal loss, and recovery submits no game action.

Windows file opens and replacement of the same prepared file have at most four attempts with 170 ms cumulative backoff. Stream writes, flush, fsync, process-lock acquisition and game submission are not retried. Persistent access errors still fail; permissions and checkpoints are preserved. Fixed numeric I/O diagnostics aid future diagnosis without exposing paths or exception text. functions.exec uses the default callMcp helper in `prompts/mcp-evidence.js`; registered evidence uses recordMcp. Both retain the original action ID after host errors or absent DTOs and protect uncertain submissions. Load the complete helper as described in [network recovery](network-recovery.md); other clients must enforce the same narrow contract.

The [activity viewer](activity.md) is separate from the preparation launcher. A new permitted MCP game launch requests it automatically; double-click `Balatro Status.exe` to reopen it without installation. `Balatro Agent.exe --monitor` remains available. Closing it does not stop gameplay or discard records. The interface displays submitted rationale and plans; it cannot retrieve unsubmitted internal reasoning.

## Developer checks and source delivery

`scripts/project.py` is the maintenance entry point. Use Python 3.13 with the project environment and `uv.lock`; the fixed sources and runtime manifest are under `config/`. From the project folder:

```powershell
.venv/Scripts/python.exe scripts/project.py status
.venv/Scripts/python.exe scripts/project.py build
.venv/Scripts/python.exe scripts/project.py build-launcher
.venv/Scripts/python.exe scripts/project.py check --source-only --output runs/checks/release-check-1.3.4.json
.venv/Scripts/python.exe scripts/project.py package --check-report runs/checks/release-check-1.3.4.json --output deliverables/github-ready-1.3.4
.venv/Scripts/python.exe scripts/project.py verify-package --output runs/checks/source-validation-1.3.4.json
.venv/Scripts/python.exe scripts/project.py verify-offline --output runs/checks/offline-preparation-1.3.4.json
```

Use new report/candidate paths; do not overwrite old evidence. Source-only checks do not update the game. Independent rebuilds and offline checks operate in fresh project-local directories and block real game transport. Private native-function fixtures are excluded from public source, and corresponding public tests skip when absent.

Public candidate verification allows 300 seconds for its full test suite and 120 seconds for each other stage. A timeout retains partial output and a failed report, stops later stages, and creates no successful validation companion. These limits apply to developer checks, separately from game-request deadlines. Preserve failed candidates and reports before preparing a replacement.

Public source contains only selected code, documentation, fixed licensed distributions, current experience baselines and selected historical evidence. Exclude personal configuration, environments, artifacts, live records, saves, seeds, keys, private game materials, TEST and backups. Verify each candidate member against its manifest before publication. Source checks, independent builds, offline preparation, client reload and real gameplay are separate evidence. Push only with explicit authorization; source publication does not automatically create a GitHub Release or tag.

[Chinese detailed maintenance reference](maintenance.md) · [English MCP setup](model-client.en.md) · [English support scope](english-support.md).
