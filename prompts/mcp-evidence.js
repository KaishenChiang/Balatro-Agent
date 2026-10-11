// Host-side orchestration only: no model API, strategy, game transport or process restart.
function mcpDto(raw) {
  const object = value => value !== null && typeof value === 'object' &&
    !Array.isArray(value) && Object.keys(value).length > 0;
  if (!object(raw) || raw.isError === true) return null;
  if (object(raw.structuredContent)) return raw.structuredContent;
  if (Array.isArray(raw.content)) {
    const block = raw.content.find(value => value.type === 'text');
    if (block) { try { const value = JSON.parse(block.text); if (object(value)) return value; } catch {} }
  }
  if (!('content' in raw) && !('structuredContent' in raw) && !('isError' in raw)) return raw;
  return null;
}

function hostApprovalTimeout(raw) {
  // Exact host fail-closed receipt only. Missing records, arbitrary errors,
  // denials and text contained in a successful game DTO are not this receipt.
  const message = 'The automatic permission approval review did not finish before its deadline. ' +
    'Do not assume the action is unsafe based on the timeout alone. ' +
    'You may retry once, or ask the user for guidance or explicit approval.';
  return raw?.isError === true && raw.structuredContent == null &&
    Array.isArray(raw.content) && raw.content.length === 1 &&
    raw.content[0].type === 'text' && typeof raw.content[0].text === 'string' &&
    raw.content[0].text.trim() === message;
}

async function callMcp(tool, parameters, delivery) {
  // Optional evidence recording is supplied as a callback. Every actual call,
  // including a failed approval and the read-only checks, is delivered separately.
  if (load('balatro_evidence_pending')) throw Error('Persist previous delivery before continuing');
  const allowed = ['health','observe','wait_until_ready','act','action_status','read_notes',
    'write_note','run_plan','calculate','launch_game','close_game','recover_lost_session'];
  if (!allowed.includes(tool)) throw Error('Unsupported tool');
  // Clone before awaiting: a caller cannot mutate the approved retry's content.
  const request = JSON.parse(JSON.stringify(parameters));
  const previousObservation = load('balatro_mcp_current_observation');
  const session = /^obs-([a-f0-9]{16})-\d+$/.exec(request.observation_id || '')?.[1];
  async function invoke(name, args, retry = false) {
    const uncertain = load('balatro_evidence_uncertain');
    if (load('balatro_evidence_pending')) throw Error('Persist previous delivery before continuing');
    if (uncertain) {
      const originalQuery = name === 'action_status' && args.action_id === uncertain.actionId;
      const recovery = name === 'recover_lost_session' && args.action_id === uncertain.actionId;
      if (name !== 'observe' && !originalQuery && !recovery && !retry)
        throw Error('Uncertain action: query the original ID and observe; never replay or advance');
    }
    const method = 'mcp__balatro_agent__' + name;
    if (typeof tools[method] !== 'function') throw Error('Actual MCP tool is not loaded');
    // Consume the only approval retry before invoking the host. If its response
    // is lost, the original non-execution receipt cannot authorize another try.
    if (retry) store('balatro_evidence_uncertain', {...uncertain,
      state:'UNKNOWN', hostApprovalTimeout:false, retryUsed:true});
    const started = Date.now();
    let raw;
    try { raw = await tools[method](JSON.parse(JSON.stringify(args))); }
    catch { raw = {isError:true}; }
    const ended = Date.now();
    const dto = mcpDto(raw);
    // Retain complete host results in host memory; never present them as game DTOs.
    store('balatro_mcp_last_raw', raw ?? null);
    if (name === 'act' && (!dto || ['RUNNING','UNKNOWN'].includes(dto.state))) {
      store('balatro_evidence_uncertain', {actionId:args.action_id,
        state:dto?.state || 'UNKNOWN', hostApprovalTimeout:hostApprovalTimeout(raw),
        gameSession:/^obs-([a-f0-9]{16})-\d+$/.exec(args.observation_id || '')?.[1],
        retryUsed:retry || uncertain?.retryUsed === true,
        ...(hostApprovalTimeout(raw) && !retry ? {originalRequest:request,
          retryObservation:{observation_id:previousObservation?.observation_id,
            profile:previousObservation?.profile}, approvalReceipt:raw} : {})});
    } else if (uncertain && name === 'action_status' && dto?.action_id === uncertain.actionId &&
        (!uncertain.gameSession || dto.game_session === uncertain.gameSession) &&
        (dto.state === 'COMPLETED' || dto.state === 'REJECTED' && dto.submitted === false ||
         dto.state === 'AWAITING_INPUT' && dto.required_action === 'close_menu')) {
      store('balatro_evidence_uncertain', null);
    } else if (uncertain && name === 'recover_lost_session' && dto?.action_id === uncertain.actionId &&
        dto.state === 'RETIRED' && dto.write_state === 'COMMITTED') {
      store('balatro_evidence_uncertain', null);
    } else if (name === 'act' && dto?.action_id === args.action_id &&
        (!session || dto.game_session === session) &&
        (dto.state === 'COMPLETED' || dto.state === 'REJECTED' && dto.submitted === false)) {
      store('balatro_evidence_uncertain', null);
    }
    if (dto?.observation && !dto.public_changes?.reason?.startsWith('historical_'))
      store('balatro_mcp_current_observation', dto.observation);
    const value = delivery ? await delivery(name, args, raw, started, ended) : raw;
    return {raw, dto, value};
  }

  async function query(name, args) {
    let result = await invoke(name, args);
    for (const delay of [250, 500]) {
      if (!(['disconnected','request_timeout'].includes(result.dto?.status) ||
          result.dto?.state === 'UNKNOWN' && result.dto.reason === 'transport_uncertain')) break;
      await new Promise(resolve => setTimeout(resolve, delay));
      result = await invoke(name, args);
    }
    return result;
  }
  async function recoverApproval(result, waiting) {
    const expected = waiting.retryObservation;
    if (!session || expected?.observation_id !== request.observation_id ||
        ![1,2,3].includes(expected?.profile)) return result.value;
    const status = await query('action_status', {action_id:request.action_id, view:request.view || 'compact'});
    if (status.dto?.action_id !== request.action_id || status.dto.game_session !== session) return result.value;
    if (status.dto.state === 'COMPLETED' || status.dto.state === 'REJECTED' && status.dto.submitted === false)
      return status.value; // An actual record resolves the call without replay.
    if (status.dto.state !== 'UNKNOWN' || status.dto.reason !== 'record_not_found' ||
        status.dto.submitted != null) return result.value;
    const observed = await query('observe', {view:request.view || 'compact'});
    const current = observed.dto?.observation;
    if (observed.dto?.status !== 'ok' || current?.ready !== true ||
        current.observation_id !== request.observation_id || current.profile !== expected.profile)
      return result.value;
    // Host receipt proves this invocation did not run; records/state alone never do.
    // One identical retry still passes host approval and every server/native guard.
    return (await invoke('act', request, true)).value;
  }
  // Short query failures are safe to retry; submissions never enter this loop.
  if (['health','observe','wait_until_ready','action_status'].includes(tool))
    return (await query(tool, request)).value;
  const waiting = load('balatro_evidence_uncertain');
  if (tool === 'act' && waiting?.hostApprovalTimeout && !waiting.retryUsed &&
      JSON.stringify(waiting.originalRequest) === JSON.stringify(request)) {
    // Resume only preflight after a failed query batch; no act has been retried yet.
    const raw = waiting.approvalReceipt;
    return recoverApproval({raw, value:delivery ? {status:'external_tool_error',isError:true} : raw}, waiting);
  }
  const result = await invoke(tool, request);
  if (tool !== 'act' || !hostApprovalTimeout(result.raw)) return result.value;
  return recoverApproval(result, load('balatro_evidence_uncertain'));
}

async function recordMcp(tool, parameters) {
  const ctx = load('balatro_evidence_context');
  if (!ctx || !/^n5-[a-z0-9-]{1,70}$/.test(ctx.runId)) throw Error('Register evidence first');
  if (typeof ctx.workspaceRoot !== 'string' || /[\r\n]/.test(ctx.workspaceRoot)) throw Error('Missing workspace root');
  return callMcp(tool, parameters, recordMcpDelivery);
}

async function recordMcpDelivery(tool, parameters, raw, started, ended) {
  const ctx = load('balatro_evidence_context');
  const dto = mcpDto(raw) || {status:'external_tool_error',isError:true};
  const hostError = dto.status === 'external_tool_error' && dto.isError === true;
  const step = (ctx.step || 0) + 1;
  const row = {step,tool,parameters,result:dto,
    client_started_utc:new Date(started).toISOString(),client_finished_utc:new Date(ended).toISOString(),
    client_tool_ms:ended-started,inter_call_gap_ms:ctx.finishedAt == null ? null : started-ctx.finishedAt,
    current_chat_id:ctx.threadId || 'not_exposed',formal_game:false};
  if (hostError) {
    row.evidence_type = 'host_tool_error_not_mcp_delivery';
    if (hostApprovalTimeout(raw)) row.host_failure = 'approval_timeout_not_executed';
  }
  store('balatro_evidence_pending',row);
  store('balatro_last_delivery',dto);
  const file = 'runs/optimization/' + ctx.runId + '/.call-' + String(step).padStart(4,'0') + '.json';
  const patch = '*** Begin Patch\n*** Add File: ' + ctx.workspaceRoot.replace(/\\/g,'/').replace(/\/$/,'') + '/' + file + '\n+' + JSON.stringify(row) + '\n*** End Patch';
  const staged = await tools.apply_patch(patch);
  if (staged && staged.isError) throw Error('Evidence spool failed; stop and preserve delivery');
  const written = await tools.exec_command({cmd:'.venv/Scripts/python.exe scripts/client_evidence.py --run-id ' + ctx.runId + ' --payload-file ' + file,workdir:ctx.workspaceRoot,max_output_tokens:100});
  if (written.exit_code !== 0) throw Error('Evidence append failed; preserve delivery and spool');
  store('balatro_evidence_context',{...ctx,step,finishedAt:ended});
  store('balatro_evidence_pending',null);
  return dto;
}
