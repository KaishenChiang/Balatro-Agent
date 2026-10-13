"""Host approval recovery with stub tools; no live game or approval requests."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


TIMEOUT = ('The automatic permission approval review did not finish before its deadline. '
           'Do not assume the action is unsafe based on the timeout alone. '
           'You may retry once, or ask the user for guidance or explicit approval.')
QUOTA = ('Automatic approval review failed: Error running remote compact task: '
         'You’ve hit your usage limit. Upgrade to Pro (https://chatgpt.com/explore/pro), '
         'visit https://chatgpt.com/settings/usage to purchase more credits or try again at 8:53 PM.\n'
         'The action was not executed because automatic approval review could not be completed. '
         'This is a review failure, not a determination that the action is unsafe. '
         'Do not bypass the approval check; resolve the error or ask the user for guidance.')
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
    if(acts>=3 && input.repeatAfterQuota)return input.manualError;
    if(acts===2)retryConsumed=data.get('balatro_evidence_uncertain')?.retryUsed===true;
    if(input.retryThrows)throw Error('Lost host response');
    return input.retryError || wrap(input.retryDto || {state:'COMPLETED',action_id:p.action_id,game_session:session,submitted:true});
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
  mcp__balatro_agent__health:async p=>{calls.push(['health',p]);return wrap({status:'ok'});},
  mcp__balatro_agent__wait_until_ready:async p=>{calls.push(['wait_until_ready',p]);return wrap({status:'ready'});},
  mcp__balatro_agent__read_notes:async p=>{calls.push(['read_notes',p]);return wrap({status:'ok'});},
  mcp__balatro_agent__calculate:async p=>{calls.push(['calculate',p]);return wrap({status:'ok'});},
  mcp__balatro_agent__launch_game:async p=>{calls.push(['launch_game',p]);return wrap(input.launch || {state:'COMPLETED'});},
  apply_patch:async patch=>{rows.push(JSON.parse(patch.split('\n').find(l=>l.startsWith('+')).slice(1)));return {};},
  exec_command:async()=>({exit_code:input.persistFailure?1:0})
};
data.set('balatro_evidence_context',{runId:'n5-synthetic',workspaceRoot:'D:/synthetic'});
const api=new Function('tools','load','store',fs.readFileSync(process.argv[1],'utf8')+
  '\nreturn {callMcp,recordMcp,restoreHostNonExecution};')(tools,k=>data.get(k),(k,v)=>data.set(k,v));
(async()=>{
  const fn=input.evidence?api.recordMcp:api.callMcp;
  await api.callMcp('observe',{});
  let result, failed=false;
  try{result=await fn('act',request);}catch{failed=true;}
  if(input.mutateRaw && input.error.content?.[0])input.error.content[0].text='Caller modified this raw result';
  let migrationBlocked=false;
  if(input.migrate){
    const waiting={actionId:id,gameSession:session,state:'UNKNOWN',hostApprovalTimeout:false,
      retryUsed:!!input.migrationRetryUsed,originalRequest:structuredClone(original),
      originalRaw:structuredClone(input.migrationRaw || input.error),...input.migrationWaiting};
    for(const key of input.migrationMissing || [])delete waiting[key];
    data.set('balatro_evidence_uncertain',waiting);
    const migrated={...original,...input.migrationRequest};
    try{api.restoreHostNonExecution(migrated,input.migrationReceipt || input.error);}catch{migrationBlocked=true;}
  }
  const diagnostics=[];
  if(input.diagnostics){
    for(const tool of ['health','wait_until_ready','read_notes','calculate','launch_game']){
      try{diagnostics.push([tool,await api.callMcp(tool,{})]);}catch{diagnostics.push([tool,'blocked']);}
    }
  }
  if(input.repeatAfterQuota)await fn('act',structuredClone(original));
  if(input.queryOriginal)await fn('action_status',{action_id:id});
  let resumeBlocked=false;
  if(input.resume){
    const resumed=structuredClone(original);
    if(input.resumeChanged)resumed.reason='Changed request';
    try{result=await fn('act',resumed);}catch{resumeBlocked=true;}
  }
  let againBlocked=false;
  if(input.resumeAgain){try{await fn('act',original);}catch{againBlocked=true;}}
  let blocked=false;
  if(!input.skipNext)try{await api.callMcp('act',{...request,action_id:'next-id'});}catch{blocked=true;}
  console.log(JSON.stringify({result,failed,blocked,resumeBlocked,againBlocked,retryConsumed,calls,rows,acts,statuses,
    migrationBlocked,diagnostics,receipts:data.get('balatro_host_non_execution_receipts'),
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


@pytest.mark.parametrize('change,expected_blocked', [({}, False), ({'retired': False}, True),
    ({'normal_game_completed': True}, True), ({'action_id': 'wrong-id'}, True),
    ({'reason': 'record_not_found'}, True)])
def test_explicit_abandonment_query_releases_only_matching_archived_client_gate(change, expected_blocked):
    status = {'state': 'UNKNOWN', 'reason': 'session_abandoned', 'action_id': 'original-id',
              'submitted': None, 'read_only': True, 'retired': True,
              'original_action_state': 'UNKNOWN', 'normal_game_completed': False, **change}
    result = run(error={'isError': True}, queryOriginal=True, status=status)
    assert result['blocked'] is expected_blocked
    assert result['acts'] == (1 if expected_blocked else 2)


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


def test_quota_receipt_is_not_submitted_without_automatic_retry_and_survives_queries():
    result = run(error={'isError': True, 'content': [{'type': 'text', 'text': QUOTA}]},
                 evidence=True, skipNext=True, diagnostics=True)
    assert result['acts'] == 1 and result['statuses'] == 0
    assert result['uncertain'] is None
    assert result['receipts']['original-id']['raw']['content'][0]['text'] == QUOTA
    assert result['receipts']['original-id']['originalRequest']['action_id'] == 'original-id'
    assert result['rows'][0]['host_submission_state'] == 'NOT_SUBMITTED'
    assert all(r[1] != 'blocked' for r in result['diagnostics'])


@pytest.mark.parametrize('error', [
    {'isError': True, 'content': [{'type': 'text', 'text': QUOTA + ' extra'}]},
    {'isError': True, 'content': [{'type': 'text', 'text': QUOTA.split('\n')[0]}]},
    {'isError': True, 'content': [{'type': 'text', 'text': QUOTA}], 'structuredContent': {'state': 'UNKNOWN'}},
    {'structuredContent': {'state': 'UNKNOWN', 'message': QUOTA}},
    {'isError': True, 'content': [{'type': 'text', 'text': QUOTA}, {'type': 'text', 'text': 'other'}]},
])
def test_quota_like_text_cannot_release_real_uncertainty(error):
    result = run(error=error)
    assert result['acts'] == 1 and result['blocked']


def test_real_unknown_allows_diagnostics_but_preserves_server_launch_rejection():
    result = run(error={'structuredContent': {'state': 'UNKNOWN', 'submitted': True}},
                 diagnostics=True, launch={'state': 'REJECTED', 'reason': 'game_action_unknown'})
    assert result['acts'] == 1 and result['blocked']
    assert result['uncertain']['state'] == 'UNKNOWN'
    assert result['diagnostics'][-1][1]['structuredContent']['reason'] == 'game_action_unknown'
    assert all(r[1] != 'blocked' for r in result['diagnostics'])


def test_original_quota_receipt_can_migrate_legacy_client_only_gate_without_game_call():
    result = run(error={'isError': True, 'content': [{'type': 'text', 'text': QUOTA}]},
                 migrate=True, skipNext=True)
    assert not result['migrationBlocked'] and result['uncertain'] is None
    assert result['acts'] == 1


@pytest.mark.parametrize('change', [
    {'migrationRequest': {'action_id': 'other-id'}},
    {'migrationRequest': {'observation_id': 'obs-0123456789abcdef-3'}},
    {'migrationRetryUsed': True},
    {'error': {'isError': True}},
])
def test_legacy_migration_rejects_unbound_receipts_and_consumed_retries(change):
    result = run(**{'error': {'isError': True, 'content': [{'type': 'text', 'text': QUOTA}]},
                    'migrate': True, 'skipNext': True, **change})
    assert result['migrationBlocked'] and result['uncertain']


@pytest.mark.parametrize('content', [[None], [False], [1], [{}], []])
@pytest.mark.parametrize('is_error', [False, True])
def test_malformed_content_still_blocks_gameplay_after_an_uncertain_submission(content, is_error):
    result = run(error={'isError': is_error, 'content': content})
    assert not result['failed'] and result['acts'] == 1 and result['blocked']
    assert result['uncertain']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('change', [
    {'migrationMissing': ['originalRequest']},
    {'migrationMissing': ['originalRaw']},
    {'migrationMissing': ['retryUsed']},
    {'migrationMissing': ['hostApprovalTimeout']},
    {'migrationWaiting': {'state': 'RUNNING'}},
    {'migrationWaiting': {'state': 'NOT_SUBMITTED'}},
    {'migrationWaiting': {'hostApprovalTimeout': True}},
    {'migrationRaw': {'structuredContent': {'state': 'UNKNOWN', 'submitted': True}}},
    {'migrationRaw': {'isError': True}},
    {'migrationRequest': {'action': 'play'}},
    {'migrationRequest': {'parameters': {'region': 'hand', 'positions': [1]}}},
    {'migrationRequest': {'reason': 'Other request'}},
    {'migrationRequest': {'observation_id': 'obs-fedcba9876543210-4'}},
    {'migrationReceipt': {'isError': True, 'content': [{'type': 'text',
        'text': QUOTA.replace('8:53 PM', '9:53 PM')}]}},
])
def test_migration_never_substitutes_a_receipt_or_invents_missing_original_call_evidence(change):
    result = run(error={'isError': True, 'content': [{'type': 'text', 'text': QUOTA}]},
                 migrate=True, skipNext=True, **change)
    assert result['migrationBlocked'] and result['uncertain']
    assert result['acts'] == 1


def test_failed_evidence_persistence_also_blocks_manual_migration():
    result = run(error={'isError': True, 'content': [{'type': 'text', 'text': QUOTA}]},
                 evidence=True, persistFailure=True, migrate=True, skipNext=True)
    assert result['failed'] and result['pending'] and result['migrationBlocked']


@pytest.mark.parametrize('message', [
    QUOTA.replace('Upgrade to Pro', 'The action was executed. Upgrade to Pro'),
    QUOTA.replace('https://chatgpt.com/settings/usage', 'https://example.com/settings/usage'),
    QUOTA.replace('8:53 PM', '25:99 PM'),
    QUOTA.replace('8:53 PM.', '8:53 PM. Other assertions.'),
    QUOTA.replace('You’ve hit your usage limit.', 'You’ve hit your usage limit.\n'),
])
def test_unrecognized_or_conflicting_quota_wording_keeps_unknown_protection(message):
    result = run(error={'isError': True, 'content': [{'type': 'text', 'text': message}]})
    assert result['acts'] == 1 and result['blocked'] and result['uncertain']
    assert not result.get('receipts')


@pytest.mark.parametrize('message', [QUOTA.replace('8:53 PM', '12:01 AM'),
                                    QUOTA.replace('You’ve', "You've")])
def test_known_quota_receipt_accepts_clock_and_apostrophe_variants_without_retry(message):
    result = run(error={'isError': True, 'content': [{'type': 'text', 'text': message}]}, skipNext=True)
    assert result['acts'] == 1 and result['uncertain'] is None
    assert result['receipts']['original-id']['state'] == 'NOT_SUBMITTED'


def test_quota_after_timeout_retry_cannot_rearm_that_action_retry_allowance():
    result = run(retryError={'isError': True, 'content': [{'type': 'text', 'text': QUOTA}]},
                 repeatAfterQuota=True,
                 manualError={'isError': True, 'content': [{'type': 'text', 'text': TIMEOUT}]},
                 skipNext=True)
    assert result['acts'] == 3 and result['statuses'] == 1
    assert result['receipts']['original-id']['retryUsed'] is True
    assert result['uncertain']['retryUsed'] is True


@pytest.mark.parametrize('dto', [
    {'status': 'disconnected'},
    {'state': 'OTHER'},
    {'state': 'COMPLETED', 'action_id': 'other-id', 'game_session': 'fedcba9876543210', 'submitted': True},
    {'state': 'COMPLETED', 'action_id': 'original-id', 'game_session': 'fedcba9876543210', 'submitted': False},
    {'state': 'REJECTED', 'action_id': 'original-id', 'submitted': True},
    {'state': 'AWAITING_INPUT', 'action_id': 'original-id', 'game_session': 'fedcba9876543210', 'submitted': True},
])
def test_unbound_or_unclassified_action_dto_cannot_leave_gameplay_unprotected(dto):
    result = run(error={'structuredContent': dto})
    assert result['acts'] == 1 and result['blocked'] and not result['failed']
    assert result['uncertain']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('message', [QUOTA + ' unknown wording', QUOTA])
def test_original_receipt_copy_survives_caller_mutation_of_the_returned_raw(message):
    result = run(error={'isError': True, 'content': [{'type': 'text', 'text': message}]},
                 mutateRaw=True, skipNext=True)
    saved = result['uncertain']['originalRaw'] if result['uncertain'] else result['receipts']['original-id']['raw']
    assert saved['content'][0]['text'] == message


@pytest.mark.parametrize('reason', ['invalid_request', 'unknown_action'])
def test_native_prevalidation_rejection_allows_corrected_request(reason):
    result = run(error={'structuredContent': {'state': 'REJECTED', 'submitted': False,
                 'action_id': None, 'read_only': False, 'reason': reason}})
    assert result['acts'] == 2 and not result['blocked'] and result['uncertain'] is None


@pytest.mark.parametrize('change', [{'reason': 'arbitrary'}, {'read_only': None},
                                   {'read_only': True}, {'submitted': None}, {'submitted': True},
                                   {'action_id': 'other-id'}])
def test_unbound_rejection_without_exact_prevalidation_shape_remains_unknown(change):
    dto = {'state': 'REJECTED', 'submitted': False, 'action_id': None,
           'read_only': False, 'reason': 'invalid_request', **change}
    result = run(error={'structuredContent': dto})
    assert result['acts'] == 1 and result['blocked'] and result['uncertain']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('state,submitted,required', [
    ('COMPLETED', False, None), ('COMPLETED', None, None),
    ('AWAITING_INPUT', None, 'close_menu'), ('AWAITING_INPUT', False, 'close_menu'),
])
@pytest.mark.parametrize('approval_timeout', [False, True])
def test_incomplete_status_dto_cannot_clear_gate_or_authorize_retry(state, submitted, required, approval_timeout):
    error = {'isError': True, 'content': [{'type': 'text', 'text': TIMEOUT}]} if approval_timeout else {'isError': True}
    status = {'state': state, 'submitted': submitted, 'required_action': required,
              'action_id': 'original-id', 'game_session': 'fedcba9876543210'}
    result = run(error=error, status=status, queryOriginal=not approval_timeout)
    assert result['acts'] == 1 and result['blocked'] and result['uncertain']
