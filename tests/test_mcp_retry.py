"""Host approval recovery with stub tools; no live game or approval requests."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


TIMEOUT = ('The automatic permission approval review did not finish before its deadline. '
           'Do not assume the action is unsafe based on the timeout alone. '
           'You may retry once, or ask the user for guidance or explicit approval.')
SOURCE = Path(__file__).resolve().parents[1] / 'prompts/mcp-evidence.js'
NODE_SCRIPT = r'''
const fs=require('fs'), input=JSON.parse(process.argv[2]), data=new Map();
const id='original-id', session='fedcba9876543210', obs='obs-'+session+'-3';
const observation={observation_id:obs,profile:2,ready:true};
const request={action:'select',parameters:{region:'hand',positions:[0]},observation_id:obs,
  action_id:id,reason:'Public selection',experience_refs:[],view:'compact'};
const original=structuredClone(request);
let acts=0, observations=0, statuses=0;
let retryConsumed=false;
const calls=[], rows=[];
const wrap=structuredContent=>({structuredContent});
const tools={
  mcp__balatro_agent__act:async p=>{
    calls.push(['act',structuredClone(p)]); acts++;
    if(acts===1) {if(input.mutate)request.parameters.positions.push(1);return input.error;}
    if(acts===2)retryConsumed=data.get('balatro_evidence_uncertain')?.retryUsed===true;
    if(input.retryThrows)throw Error('Lost host response');
    return input.retryError || wrap(input.retryDto || {state:'COMPLETED',action_id:id,game_session:session,submitted:true});
  },
  mcp__balatro_agent__action_status:async p=>{
    calls.push(['action_status',p]);statuses++;
    return wrap(input.status || {state:'UNKNOWN',reason:'record_not_found',action_id:id,
      game_session:session,submitted:null});
  },
  mcp__balatro_agent__observe:async p=>{
    calls.push(['observe',p]);observations++;
    if(observations>1 && (input.queryFailure || observations<=1+(input.queryFailures||0)))
      return wrap({status:'disconnected'});
    return wrap({status:'ok',observation:observations===1?observation:{...observation,...input.observation}});
  },
  apply_patch:async patch=>{rows.push(JSON.parse(patch.split('\n').find(l=>l.startsWith('+')).slice(1)));return {};},
  exec_command:async()=>({exit_code:input.persistFailure?1:0})
};
data.set('balatro_evidence_context',{runId:'n5-synthetic',workspaceRoot:'D:/synthetic'});
const api=new Function('tools','load','store',fs.readFileSync(process.argv[1],'utf8')+
  '\nreturn {callMcp,recordMcp};')(tools,k=>data.get(k),(k,v)=>data.set(k,v));
(async()=>{
  const fn=input.evidence?api.recordMcp:api.callMcp;
  await api.callMcp('observe',{});
  let result, failed=false;
  try{result=await fn('act',request);}catch{failed=true;}
  let resumeBlocked=false;
  if(input.resume){
    const resumed=structuredClone(original);
    if(input.resumeChanged)resumed.reason='Changed request';
    try{result=await fn('act',resumed);}catch{resumeBlocked=true;}
  }
  let againBlocked=false;
  if(input.resumeAgain){try{await fn('act',original);}catch{againBlocked=true;}}
  let blocked=false;
  try{await api.callMcp('act',{...request,action_id:'next-id'});}catch{blocked=true;}
  console.log(JSON.stringify({result,failed,blocked,resumeBlocked,againBlocked,retryConsumed,calls,rows,acts,statuses,
    uncertain:data.get('balatro_evidence_uncertain'),pending:data.get('balatro_evidence_pending')}));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''


def run(**changes):
    node = shutil.which('node')
    if node is None:
        pytest.skip('Optional Node runtime absent')
    value = {'error': {'isError': True, 'content': [{'type': 'text', 'text': TIMEOUT}]}, **changes}
    completed = subprocess.run([node, '-e', NODE_SCRIPT, str(SOURCE), json.dumps(value)],
                               capture_output=True, text=True, encoding='utf-8', check=True, timeout=10)
    return json.loads(completed.stdout)


def test_explicit_unexecuted_approval_timeout_queries_and_retries_identical_content_once():
    result = run(mutate=True, retryError={'isError': True, 'content': [{'type': 'text', 'text': TIMEOUT}]})
    assert [c[0] for c in result['calls']] == ['observe', 'act', 'action_status', 'observe', 'act']
    assert result['calls'][1][1] == result['calls'][4][1]
    assert result['calls'][4][1]['parameters']['positions'] == [0]
    assert result['blocked'] and result['uncertain']['retryUsed']


def test_successful_retry_clears_gate_without_replacing_action_identity():
    # The harness also probes the next action after completion.
    result = run()
    assert result['result']['structuredContent']['state'] == 'COMPLETED'
    assert result['calls'][1][1] == result['calls'][4][1]
    assert not result['blocked'] and result['uncertain'] is None


@pytest.mark.parametrize('error', [
    {'isError': True},
    {'isError': True, 'content': [{'type': 'text', 'text': 'Connection failed'}]},
    {'isError': True, 'content': [{'type': 'text', 'text': 'Permission denied'}]},
    {'isError': True, 'content': [{'type': 'text', 'text': TIMEOUT}], 'structuredContent': {'state': 'UNKNOWN'}},
    {'isError': True, 'content': [{'type': 'text', 'text': None}]},
    {'isError': True, 'content': [{'type': 'text', 'text': TIMEOUT + ' extra'}]},
    {'structuredContent': {'state': 'UNKNOWN', 'reason': 'record_not_found', 'message': TIMEOUT}},
    {'structuredContent': {'state': 'UNKNOWN', 'reason': 'transport_uncertain', 'submitted': True}},
])
def test_unknown_denied_or_unclassified_errors_never_retry_submission(error):
    result = run(error=error)
    assert result['acts'] == 1 and result['statuses'] == 0 and result['blocked']


@pytest.mark.parametrize('status', [
    {'state': 'UNKNOWN', 'reason': 'record_not_found', 'action_id': 'wrong-id', 'game_session': 'fedcba9876543210'},
    {'state': 'UNKNOWN', 'reason': 'record_not_found', 'action_id': 'original-id', 'game_session': '0123456789abcdef'},
    {'state': 'UNKNOWN', 'reason': 'record_not_found', 'action_id': 'original-id', 'game_session': 'fedcba9876543210', 'submitted': True},
    {'state': 'RUNNING', 'action_id': 'original-id', 'game_session': 'fedcba9876543210', 'submitted': True},
    {'state': 'COMPLETED', 'action_id': 'original-id', 'game_session': '0123456789abcdef', 'submitted': True},
])
def test_wrong_session_record_or_submitted_action_cannot_retry(status):
    result = run(status=status)
    assert result['acts'] == 1 and result['blocked']


@pytest.mark.parametrize('observation', [
    {'observation_id': 'obs-fedcba9876543210-4'},
    {'observation_id': 'obs-0123456789abcdef-3'},
    {'profile': 1}, {'profile': None}, {'ready': False},
])
def test_changed_observation_profile_or_unready_ui_blocks_retry(observation):
    result = run(observation=observation)
    assert result['acts'] == 1 and result['blocked']


def test_recovered_completed_record_returns_actual_status_without_replay():
    result = run(status={'state': 'COMPLETED', 'action_id': 'original-id',
                         'game_session': 'fedcba9876543210', 'submitted': True})
    assert result['calls'][2][0] == 'action_status'
    assert result['result']['structuredContent']['state'] == 'COMPLETED'
    assert result['calls'][3][1]['action_id'] == 'next-id'


def test_transient_query_failure_is_bounded_and_never_submits():
    result = run(queryFailure=True)
    assert result['acts'] == 1 and result['blocked']
    assert [c[0] for c in result['calls']].count('observe') == 4


def test_read_only_preflight_recovers_a_transient_disconnect_then_retries_original():
    result = run(queryFailures=1)
    assert result['result']['structuredContent']['state'] == 'COMPLETED'
    assert [c[0] for c in result['calls']][:6] == ['observe', 'act', 'action_status', 'observe', 'observe', 'act']


def test_longer_query_outage_can_resume_original_preflight_without_extra_submission():
    result = run(queryFailures=3, resume=True)
    assert result['result']['structuredContent']['state'] == 'COMPLETED'
    assert not result['resumeBlocked']
    actual = [c for c in result['calls'] if c[0] == 'act' and c[1]['action_id'] == 'original-id']
    assert len(actual) == 2 and actual[0][1] == actual[1][1]
    assert result['statuses'] == 2 and result['retryConsumed']


def test_resume_cannot_change_original_request_or_exceed_single_retry_after_response_loss():
    changed = run(queryFailures=3, resume=True, resumeChanged=True)
    assert changed['resumeBlocked'] and changed['acts'] == 1
    lost = run(queryFailures=3, resume=True, retryThrows=True, resumeAgain=True)
    assert lost['acts'] == 2 and lost['retryConsumed'] and lost['againBlocked'] and lost['blocked']
    assert lost['uncertain']['retryUsed'] and not lost['uncertain']['hostApprovalTimeout']


def test_wrong_session_retry_receipt_cannot_clear_uncertainty():
    result = run(retryDto={'state': 'COMPLETED', 'action_id': 'original-id',
                           'game_session': '0123456789abcdef', 'submitted': True})
    assert result['acts'] == 2 and result['blocked'] and result['uncertain']['retryUsed']


@pytest.mark.parametrize('change', [{'observation': {'profile': 1}},
                                   {'observation': {'observation_id': 'obs-fedcba9876543210-4'}},
                                   {'error': {'isError': True}}])
def test_delayed_resume_still_cannot_bypass_state_changes_or_unknown_host_errors(change):
    result = run(queryFailures=3, resume=True, **change)
    assert result['acts'] == 1 and result['blocked']


def test_evidence_keeps_host_failure_queries_and_retry_as_separate_calls():
    result = run(evidence=True)
    assert [r['tool'] for r in result['rows']] == ['act', 'action_status', 'observe', 'act']
    assert result['rows'][0]['host_failure'] == 'approval_timeout_not_executed'
    assert result['rows'][0]['evidence_type'] == 'host_tool_error_not_mcp_delivery'
    assert result['rows'][1]['result']['state'] == 'UNKNOWN'
    assert result['rows'][0]['parameters'] == result['rows'][3]['parameters']
    assert all(r['formal_game'] is False for r in result['rows'])


def test_failed_evidence_append_never_continues_to_query_or_retry():
    result = run(evidence=True, persistFailure=True)
    assert result['failed'] and result['blocked'] and result['pending']
    assert result['acts'] == 1 and result['statuses'] == 0
