"""Cross-checkout intents, ownership and interrupted persistence boundaries."""
from dataclasses import replace
from pathlib import Path

import pytest

from balatro_agent.installation_registry import (
    InstallationRegistry, RegistrationGuard, SCHEMA, TRACKING, atomic_json)
from balatro_agent.settings import Settings
from balatro_agent.file_io import replace_file


@pytest.fixture
def registered(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    store = InstallationRegistry(tmp_path / 'client/balatro-agent/installation.local.json')
    settings = Settings(lifecycle_file=root / 'config/game-lifecycle.local.json',
        log_dir=root / 'runs/live', registration_file=store.path)
    value = {'schema': SCHEMA, 'checkpoint_tracking': TRACKING, 'root': str(root),
        'installed_files': []}
    with store.lock():
        store.publish(value)
    return root, store, settings, value


def test_intent_survives_source_directory_becoming_unavailable(registered):
    root, store, settings, _ = registered
    guard = RegistrationGuard(settings)
    checkpoint = {'pending': {'action_id': 'original-uncertain'}, 'input_pending': None}
    local = settings.log_dir / 'executor/checkpoint.json'
    guard.persist('executor', checkpoint, lambda: atomic_json(local, checkpoint))
    retained = root.parent / 'retained-source'
    assert root.resolve().is_relative_to(root.parent.resolve())
    assert retained.resolve().is_relative_to(root.parent.resolve())
    root.rename(retained)
    with pytest.raises(ValueError, match='Unresolved'):
        store.ensure_idle(root)
    with pytest.raises(OSError, match='registration_unavailable'):
        guard.check()
    assert store.checkpoint('executor', root) == checkpoint


def test_failed_local_intent_cannot_be_replaced_by_a_new_request(registered):
    root, store, settings, _ = registered
    guard = RegistrationGuard(settings)
    checkpoint = {'pending': {'action_id': 'original-before-dispatch'}, 'input_pending': None}
    def broken_local():
        raise OSError('local disk unavailable')
    with pytest.raises(OSError):
        guard.persist('executor', checkpoint, broken_local)
    called = []
    with pytest.raises(OSError):
        guard.persist('executor', {'pending': {'action_id': 'different'}, 'input_pending': None}, lambda: called.append(True))
    assert called == []
    assert store.checkpoint('executor', root) == checkpoint


def test_clearing_pending_requires_successful_local_persistence(registered):
    root, store, settings, _ = registered
    guard = RegistrationGuard(settings)
    checkpoint = {'pending': 'original-operation'}
    local = settings.log_dir / 'lifecycle/checkpoint.json'
    guard.persist('lifecycle', checkpoint, lambda: atomic_json(local, checkpoint))
    def broken_local():
        raise OSError('local disk unavailable')
    with pytest.raises(OSError):
        guard.persist('lifecycle', {'pending': None}, broken_local)
    assert store.checkpoint('lifecycle', root) == checkpoint
    assert store.read_json(local) == checkpoint


def test_migration_prevents_old_service_from_submitting_a_new_intent(registered):
    root, store, settings, value = registered
    fresh = root.parent / 'fresh-source'
    fresh.mkdir()
    with store.lock():
        store.publish({**value, 'root': str(fresh)})
    called = []
    with pytest.raises(OSError):
        RegistrationGuard(settings).persist('executor', {'pending': {'action_id': 'old-service'}, 'input_pending': None}, lambda: called.append(True))
    assert called == []
    newer = replace(settings, lifecycle_file=fresh / 'config/game-lifecycle.local.json', log_dir=fresh / 'runs/live')
    RegistrationGuard(newer).check()
    assert list((store.path.parent / 'history').glob('*.json'))


def test_preparation_lock_blocks_new_game_intents(registered):
    root, store, settings, _ = registered
    called = []
    with store.lock():
        with pytest.raises(OSError):
            RegistrationGuard(settings).persist('executor', {'pending': {'action_id': 'while-moving'}, 'input_pending': None}, lambda: called.append(True))
    assert called == []
    store.ensure_idle(root)


def test_stale_connection_cannot_replace_another_connections_intent(registered):
    root, store, settings, _ = registered
    idle = {'pending': None, 'input_pending': None}
    original = {'pending': {'action_id': 'first-connection'}, 'input_pending': None}
    local = settings.log_dir / 'executor/checkpoint.json'
    RegistrationGuard(settings).persist('executor', original, lambda: atomic_json(local, original), expected=idle)
    called = []
    with pytest.raises(OSError):
        RegistrationGuard(settings).persist('executor', {'pending': {'action_id': 'stale-connection'}, 'input_pending': None},
            lambda: called.append(True), expected=idle)
    assert called == []
    assert store.checkpoint('executor', root) == original
    assert store.read_json(local) == original


def test_lifecycle_cannot_dispatch_while_a_game_action_is_unresolved(registered):
    root, store, settings, _ = registered
    original = {'pending': {'action_id': 'unresolved-game-action'}, 'input_pending': None}
    local = settings.log_dir / 'executor/checkpoint.json'
    RegistrationGuard(settings).persist('executor', original, lambda: atomic_json(local, original))
    called = []
    with pytest.raises(OSError):
        RegistrationGuard(settings).persist('lifecycle', {'pending': 'new-launch'}, lambda: called.append(True),
            expected={'pending': None})
    assert called == []
    assert store.checkpoint('executor', root) == original
    assert store.checkpoint('lifecycle', root) == {'pending': None}


@pytest.mark.parametrize('state', ['INTENT', 'UNKNOWN', 'COMPLETED', 'REJECTED'])
def test_lifecycle_receipt_survives_redownload_without_changing_outcome(registered, state):
    from balatro_agent.lifecycle import LifecycleJournal, Record, Receipt
    root, store, settings, _ = registered
    journal = LifecycleJournal(settings)
    record = Record(fingerprint='0' * 64, receipt=Receipt(operation_id='original-launch',
        tool='launch_game', state=state, reason='dispatch_uncertain', submitted=None))
    journal.save(record)
    journal.pending()
    journal.set_pending('original-launch')
    saved = root.parent / 'retained-history'
    (root / 'runs/live/lifecycle').rename(saved)
    restored = LifecycleJournal(settings)
    assert restored.read('original-launch') == record
    assert restored.pending() == 'original-launch'
    assert store.checkpoint('lifecycle', root) == {'pending': 'original-launch'}
    assert journal._read(saved / 'original-launch.json') == record.model_dump()


@pytest.mark.parametrize('damage', ['missing_mirror', 'changed_root', 'changed_hash', 'changed_local', 'lost_executor'])
def test_lifecycle_restore_never_overwrites_conflicts_or_erases_unknown(registered, damage):
    from balatro_agent.lifecycle import LifecycleJournal, Record, Receipt
    root, store, settings, _ = registered
    journal = LifecycleJournal(settings)
    record = Record(fingerprint='0' * 64, receipt=Receipt(operation_id='original-launch',
        tool='launch_game', state='UNKNOWN', reason='launch_timeout', submitted=True))
    journal.save(record)
    journal.pending(); journal.set_pending('original-launch')
    path = journal.root / 'original-launch.json'
    mirror = journal._independent_path('original-launch')
    if damage == 'changed_local':
        replace_file(journal.root / 'checkpoint.json', journal.root / 'checkpoint.retained')
        changed = record.model_dump(); changed['receipt']['reason'] = 'service_error'
        atomic_json(path, changed)
    else:
        replace_file(path, path.with_suffix('.retained'))
    if damage == 'missing_mirror':
        replace_file(mirror, mirror.with_suffix('.retained'))
        assert journal.read('original-launch') is None
    else:
        if damage in ('changed_root', 'changed_hash'):
            value = store.read_json(mirror)
            value['root' if damage == 'changed_root' else 'sha256'] = str(root.parent / 'other') if damage == 'changed_root' else '0' * 64
            atomic_json(mirror, value)
        if damage == 'lost_executor':
            store.write_checkpoint('executor', root, {'pending': {'action_id': 'game-unknown'}, 'input_pending': None})
        with pytest.raises(ValueError):
            journal.read('original-launch')
    assert store.checkpoint('lifecycle', root) == {'pending': 'original-launch'}
    if damage != 'changed_local':
        assert not path.exists()


def test_lifecycle_completed_duplicate_restores_receipt_with_clear_checkpoint(registered):
    from balatro_agent.lifecycle import LifecycleJournal, Record, Receipt
    root, store, settings, _ = registered
    journal = LifecycleJournal(settings)
    record = Record(fingerprint='0' * 64, receipt=Receipt(operation_id='done',
        tool='launch_game', state='COMPLETED', reason='started', submitted=True))
    journal.save(record)
    replace_file(journal.root / 'done.json', journal.root / 'done.retained')
    assert journal.read('done') == record
    store.ensure_idle(root)
