"""An evidence-only client cannot execute game actions or overwrite history."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from client_evidence import append_call


def scene(tmp_path):
    run = 'n5-test-evidence'
    folder = tmp_path/'runs/optimization'/run
    folder.mkdir(parents=True)
    log = folder/'codex-mcp.jsonl'
    header = {'evidence_type':'codex_actual_mcp_construction','run_id':run}
    log.write_text(json.dumps(header)+'\n',encoding='utf-8')
    row = {'step':1,'tool':'observe','parameters':{},'result':{'status':'ok','observation':{'ready':True}}}
    payload = folder/'.call-0001.json'
    payload.write_text(json.dumps(row),encoding='utf-8')
    return run, log, payload, row


def test_append_exact_dto_duplicate_recovery_and_conflict(tmp_path):
    run, log, payload, row = scene(tmp_path)
    assert append_call(tmp_path, run, payload) == {'recorded_step':1,'duplicate':False,'game_called':False}
    assert json.loads(log.read_text().splitlines()[-1]) == row
    before = log.read_bytes()
    payload.write_text(json.dumps(row))
    assert append_call(tmp_path, run, payload)['duplicate']
    assert log.read_bytes() == before
    payload.write_text(json.dumps({**row,'result':{'status':'different'}}))
    with pytest.raises(ValueError, match='sequence conflict'):
        append_call(tmp_path, run, payload)
    assert payload.exists() and log.read_bytes() == before


@pytest.mark.parametrize('mutation', [
    {'step':2}, {'step':True}, {'tool':'arbitrary_lua'}, {'parameters':[]}, {'result':None},
])
def test_invalid_call_preserves_log_and_spool(tmp_path, mutation):
    run, log, payload, row = scene(tmp_path)
    before = log.read_bytes()
    payload.write_text(json.dumps({**row,**mutation}))
    with pytest.raises(ValueError):
        append_call(tmp_path, run, payload)
    assert payload.exists() and log.read_bytes() == before


def test_evidence_path_cannot_escape_registered_run(tmp_path):
    run, log, payload, row = scene(tmp_path)
    before = log.read_bytes()
    with pytest.raises(ValueError):
        append_call(tmp_path, '../outside', payload)
    elsewhere = tmp_path/'elsewhere.json'
    elsewhere.write_text(json.dumps(row))
    with pytest.raises(ValueError):
        append_call(tmp_path, run, elsewhere)
    assert log.read_bytes() == before and elsewhere.exists()


@pytest.mark.parametrize('raw,host_error,expected', [
    (None, True, None),
    ({}, True, None),
    ({'structuredContent': [], 'content': []}, True, None),
    ({'isError': True, 'structuredContent': {'state': 'COMPLETED'},
      'content': [{'type': 'text', 'text': 'SECRET_HOST_ERROR'}]}, True, None),
    ({'isError': True, 'content': [{'type': 'text', 'text': '{"state":"COMPLETED"}'}]}, True, None),
    ({'content': [{'type': 'text', 'text': 'SECRET_NON_JSON_ERROR'}]}, True, None),
    ({'structuredContent': {'state': 'UNKNOWN'}}, False, {'state': 'UNKNOWN'}),
    ({'content': [{'type': 'text', 'text': '{"state":"UNKNOWN"}'}]}, False, {'state': 'UNKNOWN'}),
    ({'status': 'ok'}, False, {'status': 'ok'}),
])
def test_evidence_wrapper_separates_host_errors_and_handles_missing_structured_output(raw,host_error,expected):
    """Run JavaScript with stub tools; never contact MCP or the game."""
    import shutil
    import subprocess
    node = shutil.which('node')
    if node is None:
        pytest.skip('Optional Node runtime absent; Python evidence tests still run')
    source = Path(__file__).resolve().parents[1] / 'prompts/mcp-evidence.js'
    script = r'''
      const fs = require('fs');
      const input = JSON.parse(process.argv[2]);
      const data = new Map([['balatro_evidence_context', {runId:'n5-synthetic',workspaceRoot:'D:/synthetic'}]]);
      let called = 0, row;
      const tools = {
        mcp__balatro_agent__act: async () => {called++; return input;},
        apply_patch: async patch => {row=JSON.parse(patch.split('\n').find(line=>line.startsWith('+')).slice(1)); return {};},
        exec_command: async () => ({exit_code:0})
      };
      const record = new Function('tools','load','store',fs.readFileSync(process.argv[1],'utf8')+'\nreturn recordMcp;')
        (tools,key=>data.get(key),(key,value)=>data.set(key,value));
      record('act',{}).then(result=>console.log(JSON.stringify({result,row,called,pending:data.get('balatro_evidence_pending')})))
        .catch(error=>{console.error(error);process.exitCode=1;});
    '''
    result = subprocess.run([node, '-e', script, str(source), json.dumps(raw)],
                            capture_output=True, text=True, encoding='utf-8', check=True)
    data = json.loads(result.stdout)
    assert data['called'] == 1 and data['pending'] is None
    assert data['row']['formal_game'] is False
    assert 'SECRET' not in result.stdout
    if host_error:
        assert data['result'] == {'status': 'external_tool_error', 'isError': True}
        assert data['row']['evidence_type'] == 'host_tool_error_not_mcp_delivery'
    else:
        assert data['result'] == expected and 'evidence_type' not in data['row']


@pytest.mark.parametrize('resolution,cleared', [
    ({'state':'COMPLETED','action_id':'original-id','submitted':True}, True),
    ({'state':'COMPLETED','action_id':'wrong-id','submitted':True}, False),
    ({'state':'COMPLETED','action_id':'original-id'}, False),
    ({'state':'REJECTED','action_id':'original-id','submitted':False}, True),
    ({'state':'REJECTED','action_id':'original-id','submitted':True}, False),
    ({'state':'UNKNOWN','action_id':'original-id'}, False),
    ({'state':'AWAITING_INPUT','action_id':'original-id','required_action':'close_menu','submitted':True}, True),
    ({'state':'AWAITING_INPUT','action_id':'original-id','required_action':'close_menu'}, False),
    ({'state':'AWAITING_INPUT','action_id':'original-id'}, False),
])
def test_evidence_host_failure_blocks_replay_until_original_query_is_resolved(resolution,cleared):
    import shutil
    import subprocess
    node = shutil.which('node')
    if node is None:
        pytest.skip('Optional Node runtime absent')
    source = Path(__file__).resolve().parents[1] / 'prompts/mcp-evidence.js'
    script = r'''
      const fs=require('fs');
      const resolution=JSON.parse(process.argv[2]);
      const data=new Map([['balatro_evidence_context',{runId:'n5-synthetic',workspaceRoot:'D:/synthetic'}]]);
      const called=[];
      const tools={
        mcp__balatro_agent__act:async p=>{called.push(['act',p.action_id]);return {isError:true};},
        mcp__balatro_agent__observe:async()=>{called.push(['observe']);return {structuredContent:{status:'ok'}};},
        mcp__balatro_agent__action_status:async p=>{called.push(['status',p.action_id]);return {structuredContent:resolution};},
        apply_patch:async()=>({}),exec_command:async()=>({exit_code:0})
      };
      const record=new Function('tools','load','store',fs.readFileSync(process.argv[1],'utf8')+'\nreturn recordMcp;')
        (tools,k=>data.get(k),(k,v)=>data.set(k,v));
      (async()=>{
        await record('act',{action_id:'original-id'});
        let replayBlocked=false,wrongQueryBlocked=false;
        try{await record('act',{action_id:'another-id'});}catch{replayBlocked=true;}
        try{await record('action_status',{action_id:'wrong-id'});}catch{wrongQueryBlocked=true;}
        await record('observe',{});
        await record('action_status',{action_id:'original-id'});
        console.log(JSON.stringify({called,replayBlocked,wrongQueryBlocked,cleared:data.get('balatro_evidence_uncertain')==null}));
      })().catch(e=>{console.error(e);process.exitCode=1;});
    '''
    value = subprocess.run([node,'-e',script,str(source),json.dumps(resolution)],
                           capture_output=True,text=True,encoding='utf-8',check=True)
    result = json.loads(value.stdout)
    assert result['replayBlocked'] and result['wrongQueryBlocked']
    assert result['cleared'] is cleared
    assert result['called'] == [['act','original-id'],['observe'],['status','original-id']]
