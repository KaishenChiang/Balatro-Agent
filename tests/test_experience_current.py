"""Synthetic storage tests only; no gameplay or strategy claims."""
from dataclasses import replace
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import zipfile

import pytest

from balatro_agent.local_audit import canonical
from balatro_agent.notes import NotesService, NotesStore, render


def content(label):
    return {'sources': [{'run_id': 'n5-synthetic-current-storage', 'steps': [1]}],
            'facts': ['SYNTHETIC ONLY ' + label], 'interpretation': ['Not strategy.'],
            'conditions': ['Isolated temporary directory.'], 'counterexamples': ['Not gameplay.'],
            'confidence': 'low', 'revision_reason': label}


def commit(store, label, revision, write_id):
    return store.write(store.request('experience', 'EXP-CURRENT', content(label), revision, write_id))


def legacy(root, labels):
    store = NotesStore(root)
    folder = root / 'experience/EXP-CURRENT'
    folder.mkdir(parents=True)
    for revision, label in enumerate(labels, 1):
        request = store.request('experience', 'EXP-CURRENT', content(label), revision-1, 'legacy-'+str(revision))
        row = {'schema_version': 'notes-1', 'kind': 'experience', 'note_id': 'EXP-CURRENT',
               'revision': revision, 'created_utc': datetime.now(timezone.utc).isoformat(),
               'write_id': request['write_id'], 'request_hash': store._hash(request), 'content': request['content']}
        (folder / f'r{revision:04d}.md').write_text(render(row), encoding='utf-8', newline='\n')
    (folder / 'HEAD.json').write_text(canonical({key: row[key] for key in ('schema_version','kind','note_id','revision')}), encoding='utf-8')
    return store


def migration_module():
    path = Path(__file__).resolve().parents[1] / 'scripts/migrate_experience_current.py'
    spec = importlib.util.spec_from_file_location('synthetic_experience_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_updates_replace_one_file_and_old_duplicate_cannot_rewind(tmp_path):
    store = NotesStore(tmp_path)
    commit(store, 'first', 0, 'write-1')
    commit(store, 'second', 1, 'write-2')
    path = tmp_path/'experience/EXP-CURRENT/current.md'
    before = path.read_bytes()
    old = commit(store, 'first', 0, 'write-1')
    assert old['duplicate'] and old['historical_receipt']
    assert old['note']['revision'] == 1 and old['note']['current_revision'] == 2
    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir()] == ['current.md']
    assert store.read(view='content')['notes'][0]['content'] == content('second')
    assert 'SYNTHETIC ONLY first' not in path.read_text(encoding='utf-8')
    with pytest.raises(Exception, match='id_conflict'):
        commit(store, 'different', 0, 'write-1')


def test_failed_update_keeps_old_content_and_is_retryable(tmp_path, settings, monkeypatch):
    service = NotesService(replace(settings, notes_dir=tmp_path))
    assert service.write_note('EXP-CURRENT', content('first'), 0, 'write-1')['status'] == 'ok'
    path = tmp_path/'experience/EXP-CURRENT/current.md'
    before = path.read_bytes()
    original = os.replace
    def fail(source, destination):
        if Path(destination).name == 'current.md':
            raise OSError('SYNTHETIC replacement failure')
        original(source, destination)
    monkeypatch.setattr(os, 'replace', fail)
    assert service.write_note('EXP-CURRENT', content('second'), 1, 'write-2')['write_state'] == 'NOT_COMMITTED'
    assert path.read_bytes() == before
    monkeypatch.setattr(os, 'replace', original)
    fresh = NotesService(replace(settings, notes_dir=tmp_path))
    assert fresh.write_note('EXP-CURRENT', content('second'), 1, 'write-2')['write_state'] == 'COMMITTED'
    assert fresh.read_notes(view='content')['notes'][0]['content'] == content('second')


def test_legacy_local_store_requires_migration_before_write(tmp_path, settings):
    store = legacy(tmp_path, ['first', 'second'])
    before = {p.name:p.read_bytes() for p in (tmp_path/'experience/EXP-CURRENT').iterdir()}
    service = NotesService(replace(settings, notes_dir=tmp_path))
    assert service.read_notes(view='content')['notes'][0]['content'] == content('second')
    assert service.write_note('EXP-CURRENT', content('third'), 2, 'write-3')['status'] == 'migration_required'
    assert {p.name:p.read_bytes() for p in (tmp_path/'experience/EXP-CURRENT').iterdir()} == before


def test_migration_archives_exact_members_and_preserves_each_latest_content(tmp_path):
    module = migration_module()
    base = legacy(tmp_path/'experience', ['base-one','base-two'])
    local = legacy(tmp_path/'runs/local-experience', ['local-one','local-two','local-three'])
    before = {p.relative_to(tmp_path).as_posix():p.read_bytes()
              for root in (base.root,local.root) for p in root.rglob('*') if p.is_file()}
    plan = module.migrate(tmp_path)
    assert plan['state'] == 'PLANNED' and plan['topics'] == 2
    assert not list(tmp_path.rglob('current.md'))
    result = module.migrate(tmp_path, apply=True)
    assert result['state'] == 'COMPLETED' and result['content_unchanged']
    with zipfile.ZipFile(tmp_path/result['archive']) as bundle:
        for name,data in before.items(): assert bundle.read(name) == data
    assert base.read(view='content')['notes'][0]['content'] == content('base-two')
    assert local.read(view='content')['notes'][0]['content'] == content('local-three')
    assert all([p.name for p in (root/'experience/EXP-CURRENT').iterdir()] == ['current.md']
               for root in (base.root,local.root))
    assert module.migrate(tmp_path, apply=True)['state'] == 'ALREADY_CURRENT'


def test_archive_verification_failure_never_changes_experience(tmp_path, monkeypatch):
    module = migration_module()
    store = legacy(tmp_path/'experience', ['first','second'])
    before = {p.name:p.read_bytes() for p in (store.root/'experience/EXP-CURRENT').iterdir()}
    original = zipfile.ZipFile.read
    def corrupt(self, name, *args, **kwargs):
        data = original(self, name, *args, **kwargs)
        return data+b'SYNTHETIC' if name.endswith('r0001.md') else data
    monkeypatch.setattr(zipfile.ZipFile, 'read', corrupt)
    with pytest.raises(ValueError, match='Archive member mismatch'):
        module.migrate(tmp_path, apply=True)
    assert {p.name:p.read_bytes() for p in (store.root/'experience/EXP-CURRENT').iterdir()} == before
    assert not (store.root/'.writer-lock').exists()


def test_partial_cleanup_retains_archive_and_can_finish_without_content_loss(tmp_path, monkeypatch):
    module = migration_module()
    store = legacy(tmp_path/'experience', ['first','second'])
    original = Path.unlink
    def fail(path, *args, **kwargs):
        if path.name == 'r0001.md': raise OSError('SYNTHETIC cleanup failure')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', fail)
    with pytest.raises(OSError, match='cleanup failure'):
        module.migrate(tmp_path, apply=True)
    reports = list((tmp_path/'runs/checks').glob('experience-single-*.json'))
    assert json.loads(reports[0].read_text())['state'] == 'PARTIAL_FAILURE'
    assert store.read(view='content')['notes'][0]['content'] == content('second')
    monkeypatch.setattr(Path, 'unlink', original)
    assert module.migrate(tmp_path, apply=True)['state'] == 'COMPLETED'
    assert store.read(view='content')['notes'][0]['content'] == content('second')


def promotion_module():
    path = Path(__file__).resolve().parents[1] / 'scripts/promote_experience.py'
    spec = importlib.util.spec_from_file_location('synthetic_experience_promotion', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_promotion_preserves_local_and_archives_previous_baseline(tmp_path):
    baseline=NotesStore(tmp_path/'experience')
    commit(baseline,'baseline',0,'base-1')
    local=NotesStore(tmp_path/'runs/local-experience',baseline_root=baseline.root)
    commit(local,'local addition',1,'local-2')
    old=baseline._current_path('EXP-CURRENT').read_bytes()
    new=local._current_path('EXP-CURRENT').read_bytes()
    module=promotion_module()
    assert module.promote(tmp_path)['state']=='PLANNED'
    assert baseline._current_path('EXP-CURRENT').read_bytes()==old
    result=module.promote(tmp_path,apply=True)
    assert result['source_matches_local'] and result['topics_verified']==1
    assert baseline._current_path('EXP-CURRENT').read_bytes()==new
    assert local._current_path('EXP-CURRENT').read_bytes()==new
    with zipfile.ZipFile(tmp_path/result['archive']) as bundle:
        assert bundle.read('experience/experience/EXP-CURRENT/current.md')==old
        assert bundle.read('runs/local-experience/experience/EXP-CURRENT/current.md')==new
    assert module.promote(tmp_path,apply=True)['state']=='ALREADY_INTEGRATED'


def test_promotion_rejects_independent_source_changes_before_mutation(tmp_path):
    baseline=NotesStore(tmp_path/'experience')
    commit(baseline,'baseline',0,'base-1')
    local=NotesStore(tmp_path/'runs/local-experience',baseline_root=baseline.root)
    commit(local,'local branch',1,'local-2')
    commit(baseline,'independent source branch',1,'base-2')
    before=baseline._current_path('EXP-CURRENT').read_bytes()
    with pytest.raises(ValueError,match='conflict'):
        promotion_module().promote(tmp_path,apply=True)
    assert baseline._current_path('EXP-CURRENT').read_bytes()==before
    assert local.read(view='content')['notes'][0]['content']==content('local branch')
    assert not (baseline.root/'.writer-lock').exists()
    assert not (local.root/'.writer-lock').exists()


def test_chinese_guide_and_strategy_view_omit_audit_and_duplicate_body(tmp_path):
    store=NotesStore(tmp_path)
    commit(store,'evidence-only-marker',0,'write-1')
    text=store._current_path('EXP-CURRENT').read_text(encoding='utf-8')
    for value in ('sources','run_id','created_utc','write_receipts','evidence-only-marker'):
        assert value not in text
    assert text.count('## 行动判断')==1
    result=store.read(view='strategy')['notes'][0]
    assert set(result)=={'note_id','kind','revision','current_revision','content'}
    assert set(result['content'])=={'interpretation','conditions','counterexamples','confidence'}
    assert store.read(view='full')['notes'][0]['content']==content('evidence-only-marker')
    metadata=json.loads(store._metadata_path('EXP-CURRENT').read_text(encoding='utf-8'))
    assert 'content' not in metadata['candidates'][0]
    assert metadata['candidates'][0]['facts']==content('evidence-only-marker')['facts']


def test_failed_audit_prune_is_committed_and_fresh_reader_selects_current_hash(tmp_path,monkeypatch):
    store=NotesStore(tmp_path)
    commit(store,'old',0,'write-1')
    atomic=store._atomic
    def fail_prune(path,data):
        if path==store._metadata_path('EXP-CURRENT') and len(json.loads(data)['candidates'])==1:
            raise PermissionError('SYNTHETIC optional prune failure')
        return atomic(path,data)
    monkeypatch.setattr(store,'_atomic',fail_prune)
    result=commit(store,'new',1,'write-2')
    assert result['write_state']=='COMMITTED'
    assert len(json.loads(store._metadata_path('EXP-CURRENT').read_text(encoding='utf-8'))['candidates'])==2
    fresh=NotesStore(tmp_path)
    assert fresh.read()['notes'][0]['content']==content('new')
    assert commit(fresh,'new',1,'write-2')['duplicate']


@pytest.mark.parametrize('damage',['body','audit','malformed_candidate'])
def test_guide_or_audit_tampering_fails_closed(tmp_path,settings,damage):
    store=NotesStore(tmp_path)
    commit(store,'valid',0,'write-1')
    if damage=='body':
        path=store._current_path('EXP-CURRENT')
        path.write_bytes(path.read_bytes().replace(b'Not strategy.',b'Changed strategy.'))
    else:
        path=store._metadata_path('EXP-CURRENT')
        value=json.loads(path.read_text(encoding='utf-8'))
        if damage=='audit': value['candidates'][0]['facts']=['SYNTHETIC changed provenance']
        else: value['candidates']=['malformed']
        path.write_bytes(json.dumps(value).encode('utf-8'))
    assert NotesService(replace(settings,notes_dir=tmp_path)).read_notes()['status']=='store_corrupt'
