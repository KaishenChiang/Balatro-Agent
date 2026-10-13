from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from importlib.metadata import version as package_version

from .reader import Reader
from .executor import Executor
from .actions import ActionKind
from .notes import NotesService
from .calculate import Calculator
from .lifecycle import GameLifecycle
from .recovery import SessionRecovery
from .run_plan import RunPlans, failure as plan_failure

reader = Reader()
executor = Executor(reader)
notes = NotesService(reader.settings, activity=reader.activity)
calculator = Calculator(reader.settings, activity=reader.activity)
lifecycle = GameLifecycle(reader, executor)
recovery = SessionRecovery(executor)
plans = RunPlans(reader, executor, notes)
reader.plans = plans
executor.lifecycle = lifecycle
reader.supported_tools = ['health', 'observe', 'wait_until_ready', 'act', 'action_status', 'read_notes', 'write_note', 'run_plan', 'calculate', 'launch_game', 'close_game', 'recover_lost_session']
mcp = MCPServer(
    "balatro-agent", version=package_version('balatro-agent'), log_level="CRITICAL",
    instructions="The chat model alone chooses strategy. On a play request, call launch_game first to open or show the verified game, then health/observe and wait_until_ready as needed; query any already-known pending action first. Follow prompts/bootstrap.md (English: prompts/bootstrap.en.md). Play only through this MCP using public UI, current native profile and latest observation; no saves, seeds, hidden deck order, future stock or external strategy guides. Read EXP-GENERAL-GUIDE in strategy view at run start and cite fully read revisions. Act submits one native action with observation_id, unique action_id, short public reason and experience_refs. Reuse current COMPLETED observations; compact columns-v1 is lossless and public_changes is only a hint. RUNNING: query the original ID. UNKNOWN or lost response: query that ID and observe, never replay or advance gameplay; diagnose and repair autonomously under docs/balatro-ai/maintenance.md. Stop and notify only for a major problem that cannot be resolved safely. Only the exact host approval-timeout non-execution receipt permits one identical retry through callMcp after original-record and unchanged-state checks. AWAITING_INPUT: observe, close the current native prompt once and query the original navigation. Use the requested deck/mode; default one Red Deck/White Stake random non-challenge run. Highest stake compares unlocked enabled candidates across available pages and ignores locked/anonymous candidates; no locked identity verification is required. An explicitly locked requested fixed choice stops. Fixed/highest allow one attempt; only explicit climb allows normal-loss retries and verified one-level advancement. A requested New Run may replace an old run, but never restart the target or bypass pending records. Pause means no new game actions. At a normal result retain results/window, report actual deck/stake, outcome, ante/round, service wall-clock duration and note status; never automatically close or continue Endless. Amend justified experience locally after reading full current content; verify local-over-baseline-v1/local_only/single-current-v2 and read back. calculate uses supplied public numbers only. Tool details and recovery contracts remain in each tool description.",
)
annotations = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False), structured_output=True)
async def launch_game(operation_id: str, timeout_s: float = 25.0) -> dict[str, object]:
    """Windows: verify Steam AppID 2379780, launch normally and wait for MCP. A new permitted launch also requests an independent bilingual activity window; closing or failing that viewer never controls gameplay. It displays public MCP summaries, submitted reason and run_plan, not internal model reasoning. If already running, verify/show its window; UNKNOWN allows only restoring that window. timeout_s is 0-30 seconds. operation_id is durably deduplicated; identical requests query only, without reopening the viewer. No game clicks, pending-action deletion, paths, commands or process IDs."""
    return await lifecycle.launch_game(operation_id, timeout_s)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False), structured_output=True)
async def close_game(operation_id: str, observation_id: str, timeout_s: float = 15.0) -> dict[str, object]:
    """Under an explicit user close request or standing authorization for necessary maintenance closure in docs/balatro-ai/maintenance.md: normally close the verified Balatro window and confirm exit, without force kill. Requires known current profile, latest observation_id, ready, normal results or idle main menu, and no pending actions. Reject active runs/UNKNOWN. 0-30 seconds; operation_id deduplicates. An uncertain response permits querying the identical operation only."""
    return await lifecycle.close_game(operation_id, observation_id, timeout_s)


@mcp.tool(annotations=annotations, structured_output=True)
async def health() -> dict[str, object]:
    """Read connection, fixed versions, actual native profile and historical test-profile comparison. A profile mismatch is information only. Performs no game action."""
    result = await reader.health()
    result['unlock_input_protocol'] = 'native-overlay-v1'
    result['session_recovery_protocol'] = 'lost-session-v1'
    result['session_recovery_history_protocol'] = 'delivered-status-history-v1'
    result['primary_experience_note'] = 'EXP-GENERAL-GUIDE'
    result['notes_policy'] = 'local-over-baseline-v1'
    result['notes_write_scope'] = 'local_only'
    result['notes_storage_format'] = 'single-current-v2'
    result['notes_default_view'] = 'strategy'
    result['run_plan_protocol'] = 'run-plan-v1'
    result['activity_text_protocol'] = 'bilingual-tags-v1'
    result['activity_run_log_protocol'] = 'per-run-v1'
    result['activity_run_log'] = reader.activity.runs.status()
    result['transport_policy'] = 'bounded-query-retry-v1'
    return result


@mcp.tool(annotations=annotations, structured_output=True)
async def observe(view: str = 'compact') -> dict[str, object]:
    """Read the player-visible state of the current identified native profile. Unknown actual profiles are reported. server_time is service wall-clock metadata outside the observation ID, usable for run timing, not pure model thinking time. No deck order, seeds or hidden card identity. Game names and descriptions retain their current game language."""
    return await reader.observe(view)


@mcp.tool(annotations=annotations, structured_output=True)
async def wait_until_ready(timeout_s: float = 10.0, view: str = 'compact') -> dict[str, object]:
    """Poll read-only until normal UI is actionable; default 10 seconds, maximum 30. Returns ready, timeout, disconnected or unsupported. Readiness alone does not confirm an action completed."""
    return await reader.wait_until_ready(timeout_s, view)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False), structured_output=True)
async def act(action: ActionKind, parameters: dict[str, object], observation_id: str, action_id: str, reason: str, experience_refs: list[str], view: str = 'compact') -> dict[str, object]:
    """Submit one native action bound to current observation_id, unique action_id, short reason and actual experience_refs. For the bilingual activity window, reason may use '[zh-CN]Chinese rationale [en]English rationale' (replace placeholders with one concise equivalent sentence in each language, no internal reasoning); plain text remains valid. parameters: select={region,positions}; reorder={region,order}; blind={blind_slot}; buy/sell/use/take={region,position}; select_setup_option={kind:deck or stake,position}; play/discard may use {positions:[complete selection]} with positions-v1, or {} for already selected cards; others={}. native-target-v1 clicks the actual target/button; select consumable hand targets separately. Pack Tarot/Planet/Spectral immediate use is use; select_pack_card takes playing cards/Jokers or explicitly enabled consumables. Choose current visible unlocked candidates; native settings only. Random non-challenge. Identical IDs query, changed content rejects. AWAITING_INPUT: observe, close each native prompt once, query original navigation. Service UNKNOWN: pause gameplay, query the original ID and observe; continue local diagnosis, repair and isolated verification under maintenance policy, without replaying or bypassing pending records. Only an exact host approval-timeout receipt confirming no execution permits one identical client retry after original-ID and unchanged-state checks; see prompts/mcp-evidence.js."""
    return await executor.act(action, parameters, observation_id, action_id, reason, experience_refs, view)


@mcp.tool(annotations=annotations, structured_output=True)
async def action_status(action_id: str, view: str = 'compact') -> dict[str, object]:
    """Query an action record in this game session and return filtered feedback; never replay it. Session change or missing records remains UNKNOWN; no cross-process exactly-once guarantee."""
    return await executor.action_status(action_id, view)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False), structured_output=True)
async def recover_lost_session(action_id: str, observation_id: str, recovery_id: str) -> dict[str, object]:
    """First query action_status and observe. Retire only after actual session change and confirmed record loss, with known current profile, fresh observation and ready. Requires a pending intent or, with all checkpoints clear, an unambiguous missing-record status previously delivered by this service in the lost session. A missing record alone never proves non-submission. The original remains UNKNOWN; RETIRED is not success or a normal loss. No game action, replay or save read. Identical recovery_id/parameters query the durable receipt. Reject live old sessions, stale observations or unknown profiles."""
    return await recovery.recover(action_id, observation_id, recovery_id)


@mcp.tool(annotations=annotations, structured_output=True)
async def read_notes(kind: str = 'experience', note_ids: list[str] | None = None, revision: int | None = None, view: str = 'strategy', query: str | None = None, offset: int = 0) -> dict[str, object]:
    """Actually read disk, local experience over read-only baseline; TEST is separate. Each experience topic has one current.md; revision is an update counter and older content is not retained for reading. Default strategy returns only actionable rules, conditions, counterexamples and confidence, plus short update references. It omits sources, historical facts, timestamps and write IDs. Explicit content/full views include audit information; full also returns the Chinese Markdown guide. Read EXP-GENERAL-GUIDE first, then relevant topics. Omitted IDs read all, [] reads none. index returns truncated previews/revision refs, not full reading or action evidence. query is literal, at most 80 characters; pages contain 20 entries, continue with next_offset. TEST retains historical reads. Existing note text keeps its original language."""
    return notes.read_notes(kind, note_ids, revision, view, query, offset)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False), structured_output=True)
async def write_note(note_id: str, content: dict[str, object], expected_revision: int, write_id: str, kind: str = 'experience', view: str = 'strategy') -> dict[str, object]:
    """Atomically replace the same local current.md, never upload or overwrite baseline. First local edit starts from the baseline current content, without copying old versions. Before amending, explicitly read content/full to preserve current strategy and audit fields. Submit the full updated content; it replaces rather than automatically merges text. 0 creates; updates require current expected_revision. The Chinese guide contains strategy only; sources, historical facts and compact hash receipts are separate audit metadata. Default strategy response omits audit fields. Receipts deduplicate write IDs without retaining old strategy content. Legacy local data requires the maintenance migration. TEST remains separate. content: sources[{run_id,steps}], facts, interpretation, conditions, counterexamples, confidence(low/medium/high), revision_reason. Formal run IDs start n5-, TEST starts test-. Model writes from actual feedback. Read back to verify."""
    return notes.write_note(note_id, content, expected_revision, write_id, kind, view)


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False), structured_output=True)
async def run_plan(mode: str = 'read', observation_id: str | None = None, content: dict[str, object] | None = None, expected_revision: int | None = None, write_id: str | None = None) -> dict[str, object]:
    """Model-authored short run memory. read actually reads disk; omit other parameters. write requires latest observation_id, expected_revision(first 0), unique write_id and content{objective,priorities:[1-4],recheck_when:[1-4],experience_refs:[up to 6 fully read EXP-XXX@rN]}. For the bilingual activity window, objective and priorities[0] may each use '[zh-CN]Chinese summary [en]English equivalent' (replace placeholders with short matching summaries); plain text remains valid. At most 2000 UTF-8 bytes, 200 characters per item including both languages and tags. Only confirmed start_run/continue_run, actionable current run, no pending action. Same ID/content queries. Revise on material changes, read after compression. Run/profile/session changes invalidate reuse but retain history. No strategy generation or game action."""
    async with reader._tool_lock:
        if mode == 'read' and all(value is None for value in (observation_id, content, expected_revision, write_id)):
            return plans.read()
        if mode == 'write':
            return plans.write(observation_id, content, expected_revision, write_id)
        return plans.audit.deliver('run_plan', plan_failure('invalid_input'))


@mcp.tool(annotations=annotations, structured_output=True)
async def calculate(operation: str, inputs: dict[str, object]) -> dict[str, object]:
    """Explicit public numbers only. sum/difference/product/quotient/mean/median/variance_population take {values:[numbers]}; combination takes {n,k}; hypergeometric takes {population,successes,draws,min_successes,max_successes}, conditioned on uniform sampling without replacement. Up to 200 values/1000 population. Reject unknown/nonfinite values, zero divisors, extra fields and limits. No game/network reads, action recommendation, expressions or arbitrary code."""
    return calculator.calculate(operation, inputs)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
