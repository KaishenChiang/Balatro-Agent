"""Per-run editing records use only delivered public activity, never game I/O."""
import json
from pathlib import Path

import pytest

from balatro_agent.activity import ActivityJournal
from test_activity import observation, events


def state(counter=1, **changes):
    value=observation(counter)
    value.update(profile=1, **changes)
    return value


def start(journal, action_id='start', counter=1, action='start_run'):
    journal.intent({'action':action,'parameters':{},'observation_id':'obs-0123456789abcdef-0',
                    'action_id':action_id,'reason':'Begin requested run.','experience_refs':[]})
    journal.delivered('act',{'action_id':action_id,'state':'COMPLETED','observation':state(counter)})


def records(journal):
    path=journal.root/'by-run'/ (journal.runs.active['stem']+'.jsonl')
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


@pytest.mark.parametrize('outcome',['win','loss'])
def test_normal_settlement_saves_run_timeline_and_postrun_experience(settings,outcome):
    journal=ActivityJournal(settings)
    start(journal)
    journal.intent({'action':'play','parameters':{'positions':[0,1]},
        'observation_id':'obs-0123456789abcdef-1','action_id':'finish',
        'reason':'[zh-CN]当前补分足够 [en]Enough current score','experience_refs':[]})
    terminal=state(2,phase='terminal',outcome=outcome)
    journal.delivered('act',{'action_id':'finish','state':'COMPLETED','observation':terminal})
    journal.delivered('write_note',{'status':'ok','write_state':'COMMITTED','note':{'note_id':'EXP-A','revision':2}})
    rows=records(journal)
    assert journal.runs.status()['status']=='completed'
    assert rows[0]['data']['event']=='start' and rows[0]['data']['origin']=='confirmed_start'
    assert sum(row['kind']=='run' and row['data']['event']=='end' for row in rows)==1
    assert rows[-1]['kind']=='notes' and 'SECRET' not in json.dumps(rows)
    timeline=(journal.root/'by-run'/(journal.runs.active['stem']+'.txt')).read_text(encoding='utf-8')
    assert '当前补分足够' in timeline and '心得：已保存' in timeline and '不是录像时间码' in timeline
    assert ('本局结束：胜利' if outcome=='win' else '本局结束：失败') in timeline
    assert '| +00:' in timeline
    before=timeline
    journal.delivered('observe',{'status':'ok','observation':terminal})
    assert (journal.root/'by-run'/(journal.runs.active['stem']+'.txt')).read_text(encoding='utf-8')==before


def test_two_runs_use_separate_files_and_preserve_previous_result(settings):
    journal=ActivityJournal(settings);start(journal)
    journal.delivered('observe',{'status':'ok','observation':state(2,phase='terminal',outcome='loss')})
    old=journal.root/'by-run'/(journal.runs.active['stem']+'.jsonl')
    before=old.read_bytes()
    start(journal,'start-again',3)
    assert old.read_bytes()==before and len(list((journal.root/'by-run').glob('*.jsonl')))==2
    assert journal.runs.active['status']=='recording' and journal.runs.active['outcome'] is None


def test_service_restart_continues_original_log_without_claiming_new_start(settings):
    first=ActivityJournal(settings);start(first)
    stem=first.runs.active['stem']
    second=ActivityJournal(settings)
    second.delivered('observe',{'status':'ok','observation':state(2)})
    second.delivered('observe',{'status':'ok','observation':state(3,phase='terminal',outcome='win')})
    assert second.runs.active['stem']==stem and second.runs.status()['status']=='completed'
    assert sum(row['kind']=='run' and row['data']['event']=='start' for row in records(second))==1
    assert any(row['kind']=='run' and row['data']['event']=='resume' for row in records(second))


def test_midrun_attachment_is_explicitly_partial_and_old_settlement_is_not_a_new_run(settings):
    journal=ActivityJournal(settings)
    journal.delivered('observe',{'status':'ok','observation':state(1,phase='terminal',outcome='loss')})
    assert journal.runs.active is None
    journal.delivered('observe',{'status':'ok','observation':state(2)})
    assert journal.runs.active['origin']=='partial_observation'
    assert '开局时间未确认' in (journal.root/'by-run'/(journal.runs.active['stem']+'.txt')).read_text(encoding='utf-8')


def test_unknown_is_retained_and_cannot_finalize_until_original_action_is_resolved(settings):
    journal=ActivityJournal(settings);start(journal)
    journal.progress('act',{'action_id':'uncertain','state':'UNKNOWN','submitted':None})
    journal.delivered('observe',{'status':'ok','observation':state(2,phase='terminal',outcome='loss')})
    assert journal.runs.status()['status']=='recording'
    journal.delivered('action_status',{'action_id':'uncertain','state':'COMPLETED',
                                     'observation':state(2,phase='terminal',outcome='loss')})
    assert journal.runs.status()['status']=='completed'
    assert any(row['data'].get('state')=='UNKNOWN' for row in records(journal))


@pytest.mark.parametrize('restored',[False,True])
def test_historical_terminal_never_rewinds_or_finishes_current_log(settings,restored):
    journal=ActivityJournal(settings);start(journal,counter=5)
    if restored: journal=ActivityJournal(settings)
    before=(journal.root/'by-run'/(journal.runs.active['stem']+'.jsonl')).read_bytes()
    journal.delivered('action_status',{'action_id':'old','state':'COMPLETED',
                                     'observation':state(2,phase='terminal',outcome='loss')})
    assert journal.runs.status()['status']=='recording'
    assert (journal.root/'by-run'/(journal.runs.active['stem']+'.jsonl')).read_bytes()==before


def test_session_boundary_marks_interruption_instead_of_a_loss(settings):
    journal=ActivityJournal(settings);start(journal)
    old=journal.root/'by-run'/(journal.runs.active['stem']+'.jsonl')
    journal.delivered('observe',{'status':'ok','observation':state(1,observation_id='obs-fedcba9876543210-1')})
    assert journal.runs.active['origin']=='partial_observation'
    rows=[json.loads(line) for line in old.read_text(encoding='utf-8').splitlines()]
    assert rows[-1]['data']['event']=='interrupted'
    assert not any(row['kind']=='run' and row['data']['event']=='end' for row in rows)


def test_archive_failure_is_reported_without_changing_feedback_or_session_log(settings,monkeypatch):
    journal=ActivityJournal(settings)
    def fail(*args,**kwargs): raise PermissionError('SYNTHETIC')
    monkeypatch.setattr(journal.runs,'_save',fail)
    value={'status':'ok','observation':state()}
    journal.delivered('observe',value)
    assert value['status']=='ok' and events(journal)[0]['kind']=='observation'
    assert journal.runs.status()['status']=='storage_unavailable'


def test_corrupt_cursor_is_preserved_and_blocks_only_optional_run_exports(settings):
    root=settings.log_dir/'activity';root.mkdir(parents=True)
    path=root/'active-run.json';path.write_text('invalid JSON',encoding='utf-8')
    journal=ActivityJournal(settings)
    journal.delivered('observe',{'status':'ok','observation':state()})
    assert path.read_text(encoding='utf-8')=='invalid JSON'
    assert journal.runs.status()['status']=='storage_unavailable' and len(events(journal))==1


def test_native_terminal_beneath_visible_menu_still_finishes_without_extra_observation(settings):
    journal=ActivityJournal(settings);start(journal)
    journal.delivered('act',{'action_id':'final','state':'COMPLETED','completion_signal':'terminal_confirmation',
        'observation':state(2,phase='menu',underlying_phase='terminal',outcome='win')})
    assert journal.runs.status()['status']=='completed'
