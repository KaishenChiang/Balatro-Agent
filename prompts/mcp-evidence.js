async function recordMcp(tool, parameters) {
  // Used only inside the host's functions.exec. The caller supplies every
  // decision; this wrapper calls exactly one actual project MCP tool.
  const ctx = load('balatro_evidence_context');
  if (!ctx || !/^n5-[a-z0-9-]{1,70}$/.test(ctx.runId)) throw Error('Register evidence first');
  if (typeof ctx.workspaceRoot !== 'string' || /[\r\n]/.test(ctx.workspaceRoot)) throw Error('Missing workspace root');
  if (load('balatro_evidence_pending')) throw Error('Persist previous delivery before continuing');
  const allowed = ['health','observe','wait_until_ready','act','action_status','read_notes',
    'write_note','run_plan','calculate','launch_game','close_game','recover_lost_session'];
  if (!allowed.includes(tool)) throw Error('Unsupported tool');
  const uncertain = load('balatro_evidence_uncertain');
  if (uncertain) {
    const originalQuery = tool === 'action_status' && parameters.action_id === uncertain.actionId;
    const recovery = tool === 'recover_lost_session' && parameters.action_id === uncertain.actionId;
    if (tool !== 'observe' && !originalQuery && !recovery)
      throw Error('Uncertain action: query the original ID and observe; never replay or advance');
  }
  const method = 'mcp__balatro_agent__' + tool;
  if (typeof tools[method] !== 'function') throw Error('Actual MCP tool is not loaded');
  const started = Date.now();
  let raw;
  try { raw = await tools[method](parameters); }
  catch (error) {
    raw = {isError:true}; // Host exception text is not a public game DTO.
  }
  const ended = Date.now();
  const isDto = value => value !== null && typeof value === 'object' &&
    !Array.isArray(value) && Object.keys(value).length > 0;
  const usable = isDto(raw) && raw.isError !== true;
  let dto = usable ? raw.structuredContent : null;
  if (!isDto(dto) && usable && Array.isArray(raw.content)) {
    const block = raw.content.find(value => value.type === 'text');
    if (block) { try { dto = JSON.parse(block.text); } catch (error) {} }
  }
  if (!isDto(dto) && usable && !('content' in raw) &&
      !('structuredContent' in raw) && !('isError' in raw)) dto = raw;
  const hostError = !isDto(dto);
  if (hostError) dto = {status:'external_tool_error',isError:true};
  if (tool === 'act' && (hostError || ['RUNNING','UNKNOWN'].includes(dto.state))) {
    // A host error can occur before the server receives the intent. Preserve
    // the caller's ID even when no structured result supplies one.
    store('balatro_evidence_uncertain',{actionId:parameters.action_id,state:dto.state || 'UNKNOWN'});
  } else if (uncertain && tool === 'action_status' && !hostError
      && dto.action_id === uncertain.actionId
      && (dto.state === 'COMPLETED' || dto.state === 'REJECTED' && dto.submitted === false
          || dto.state === 'AWAITING_INPUT' && dto.required_action === 'close_menu')) {
    // Native input is now confirmed; the server still protects its parent
    // action and validates each fresh close_menu followed by the parent query.
    store('balatro_evidence_uncertain',null);
  } else if (uncertain && tool === 'recover_lost_session' && !hostError
      && dto.action_id === uncertain.actionId && dto.state === 'RETIRED' && dto.write_state === 'COMMITTED') {
    store('balatro_evidence_uncertain',null); // Original outcome remains UNKNOWN.
  }
  const step = (ctx.step || 0) + 1;
  const row = {step,tool,parameters,result:dto,
    client_started_utc:new Date(started).toISOString(),client_finished_utc:new Date(ended).toISOString(),
    client_tool_ms:ended-started,inter_call_gap_ms:ctx.finishedAt == null ? null : started-ctx.finishedAt,
    current_chat_id:ctx.threadId || 'not_exposed',formal_game:false};
  if (hostError) row.evidence_type = 'host_tool_error_not_mcp_delivery';
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
