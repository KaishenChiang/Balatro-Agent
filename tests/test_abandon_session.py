"""Crash/retry and anti-replay checks for explicit stopped-session abandonment."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import abandon_session as maintenance
from balatro_agent.abandonment import read_fence, fence_path
from balatro_agent.executor import Executor
from balatro_agent.installation_registry import InstallationRegistry, SCHEMA, TRACKING, atomic_json, RegistrationGuard
from balatro_agent.lifecycle import GameLifecycle
from balatro_agent.settings import Settings
from test_lifecycle import Backend, PROCESS

OLD = 'fedcba9876543210'
OBS = 'obs-' + OLD + '-1'


@pytest.fixture
def case(tmp_path):
    root = tmp_path / 'source'; root.mkdir()
    config = tmp_path / 'client/config.toml'
    store = InstallationRegistry(config.parent / 'balatro-agent/installation.local.json')
    store.publish({'schema': SCHEMA, 'checkpoint_tracking': TRACKING, 'root': str(root), 'installed_files': []})
    settings = replace(Settings(), log_dir=root / 'runs/live', lifecycle_file=root / 'config/game-lifecycle.local.json', registration_file=store.path)
    reader = SimpleNamespace(settings=settings, _tool_lock=asyncio.Lock(), _observation_profiles={OBS: 2}, last_delivered_observation={'observation_id': OBS})
    reader.observed_profile = lambda obs: reader._observation_profiles.get(obs)
    async def envelope(_): return object()
    reader._envelope = envelope
    executor = Executor(reader)
    executor.pending = {'action': 'open_run_setup', 'parameters': {}, 'action_id': 'old-nav', 'observation_id': OBS,
                        'reason': 'Synthetic navigation', 'experience_refs': []}
    executor.input_pending = {**executor.pending, 'action': 'close_menu', 'action_id': 'old-input'}
    executor._save()
    backend = Backend(); backend.process = None
    lifecycle = GameLifecycle(reader, executor, backend, poll_s=.001)
    executor.lifecycle = lifecycle
    def run(output='runs/checks/recovery-one.json', apply=True):
        return maintenance.run(root, output=output, config=config, backend=backend, apply=apply)
    return root, store, reader, executor, lifecycle, backend, run


def test_archive_preserves_parent_input_and_raw_bytes(case):
    root, store, _, executor, _, _, run = case
    before = executor.checkpoint.read_bytes()
    result = run()
    assert result['state'] == 'COMMITTED' and result['safe_to_prepare']
    assert result['original_action_state'] == 'UNKNOWN' and not result['game_action_submitted']
    assert set(result['action_ids']) == {'old-nav', 'old-input'}
    file = next(item for item in result['files'] if item['path'] == str(executor.checkpoint))
    archive = fence_path(store, root).parent.parent / 'abandoned-sessions' / fence_path(store, root).stem / 'recovery-one'
    assert (archive / file['backup']).read_bytes() == before
    store.ensure_idle(root)
    assert run()['duplicate']


@pytest.mark.parametrize('damage', ['local', 'mirror', 'both', 'missing'])
def test_damaged_or_missing_checkpoints_are_preserved_and_recoverable(case, damage):
    _, store, _, executor, _, _, run = case
    if damage in ('local', 'both'):
        executor.checkpoint.write_bytes(b'broken "action_id":"old-nav"')
    if damage in ('mirror', 'both'):
        store.checkpoint_path('executor').write_bytes(b'broken "action_id":"old-input"')
    if damage == 'missing':
        executor.checkpoint.unlink()
    assert run()['state'] == 'COMMITTED'
    assert store.checkpoint('executor', executor.registration.root) == {'pending': None, 'input_pending': None}


@pytest.mark.parametrize('index', range(1, 10))
@pytest.mark.parametrize('after_write', [False, True])
def test_every_commit_boundary_can_resume_in_a_new_launcher(case, monkeypatch, index, after_write):
    root, store, _, _, _, _, run = case
    original = maintenance.atomic_json
    calls = 0
    def fail(path, value):
        nonlocal calls
        calls += 1
        if calls == index and not after_write:
            raise OSError('synthetic interrupted write')
        original(path, value)
        if calls == index and after_write:
            raise OSError('synthetic lost write response')
    with monkeypatch.context() as patch:
        patch.setattr(maintenance, 'atomic_json', fail)
        with pytest.raises(OSError):
            run()
    # A relaunched GUI has a different ID. It must resume the pending durable
    # transaction without asking the user to recover an old GUID.
    result = run('runs/checks/new-launcher.json')
    assert result['state'] == 'COMMITTED' and result['safe_to_prepare']
    store.ensure_idle(root)
    assert read_fence(store, root)['state'] == 'COMMITTED'


def test_in_progress_fence_blocks_preparation_even_after_checkpoints_clear(case, monkeypatch):
    root, store, _, _, _, _, run = case
    original = maintenance.atomic_json
    def fail(path, value):
        if path.name == 'receipt.json' and value.get('record', {}).get('state') == 'COMMITTED':
            raise OSError('interrupted final commit')
        return original(path, value)
    with monkeypatch.context() as patch:
        patch.setattr(maintenance, 'atomic_json', fail)
        with pytest.raises(OSError): run()
    assert all(v is None for v in store.checkpoint('executor', root).values())
    with pytest.raises(ValueError, match='Unfinished'):
        store.ensure_idle(root)
    assert run('runs/checks/new-window.json')['state'] == 'COMMITTED'


def test_same_completed_id_never_clears_new_session(case):
    root, store, reader, _, _, _, run = case
    run()
    fresh = Executor(reader)
    fresh.pending = {'action': 'open_run_setup', 'parameters': {}, 'action_id': 'new-nav',
                     'observation_id': 'obs-0123456789abcdef-2', 'reason': 'New synthetic intent', 'experience_refs': []}
    fresh._save()
    assert run()['duplicate']
    assert store.checkpoint('executor', root)['pending']['action_id'] == 'new-nav'


async def test_loaded_service_refreshes_generation_and_never_replays_old_ids(case):
    _, _, reader, executor, lifecycle, backend, run = case
    run()
    result = await executor.action_status('old-input')
    assert result['state'] == 'UNKNOWN' and result['retired']
    assert executor.pending is None and executor.input_pending is None
    assert reader._observation_profiles == {} and reader.last_delivered_observation is None
    retired = await executor.act('open_run_setup', {}, OBS, 'old-nav', 'Synthetic retry', [])
    assert retired['state'] == 'UNKNOWN' and retired['retired']
    launched = await lifecycle.launch_game('fresh-launch', 0)
    assert launched['state'] == 'COMPLETED' and backend.launches == 1


async def test_lost_lifecycle_receipt_no_longer_traps_launch(case):
    root, store, _, _, lifecycle, backend, run = case
    atomic_json(root / 'runs/live/lifecycle/checkpoint.json', {'pending': 'orphan-launch'})
    store.write_checkpoint('lifecycle', root, {'pending': 'orphan-launch'})
    run()
    old = await lifecycle.launch_game('orphan-launch', 0)
    assert old['state'] == 'UNKNOWN' and old['retired'] and backend.launches == 0
    assert (await lifecycle.launch_game('new-launch', 0))['state'] == 'COMPLETED'
    assert backend.launches == 1


def test_live_or_appearing_game_and_lock_contention_do_not_release_waiting(case):
    root, store, _, _, _, backend, run = case
    backend.process = PROCESS
    with pytest.raises(ValueError, match='still running'): run()
    assert store.checkpoint('executor', root)['pending']
    backend.process = None
    with store.lock(), pytest.raises(OSError): run()
    assert store.checkpoint('executor', root)['pending']
    checks = iter([None, PROCESS])
    backend.find = lambda: next(checks)
    with pytest.raises(ValueError, match='State changed'): run()
    assert store.checkpoint('executor', root)['pending']


def test_archive_failure_and_post_intent_drift_preserve_originals(case, monkeypatch):
    root, store, _, executor, _, _, run = case
    before = executor.checkpoint.read_bytes()
    original = maintenance.atomic_json
    def fail(path, value):
        if path.name == 'receipt.json': raise OSError('archive write failed')
        return original(path, value)
    with monkeypatch.context() as patch:
        patch.setattr(maintenance, 'atomic_json', fail)
        with pytest.raises(OSError): run()
    assert executor.checkpoint.read_bytes() == before
    with monkeypatch.context() as patch:
        patch.setattr(maintenance, 'atomic_json', lambda path, value: (_ for _ in ()).throw(OSError()) if path == executor.checkpoint else original(path, value))
        with pytest.raises(OSError): run()
    executor.checkpoint.write_bytes(b'new unrelated checkpoint')
    with pytest.raises(ValueError, match='State changed'): run('runs/checks/another-window.json')
    assert executor.checkpoint.read_bytes() == b'new unrelated checkpoint'


def test_old_guard_cannot_dispatch_after_abandonment(case):
    _, _, _, executor, _, _, run = case
    run()
    calls = []
    with pytest.raises(OSError):
        with executor.registration.dispatch(): calls.append('dispatch')
    assert not calls


def test_preview_has_no_checkpoint_or_fence_mutation(case):
    root, store, _, executor, _, _, run = case
    before = executor.checkpoint.read_bytes()
    assert run(apply=False)['state'] == 'PLANNED'
    assert executor.checkpoint.read_bytes() == before and not fence_path(store, root).exists()


@pytest.mark.parametrize('value', ['[]', 'null', '{"record":[]}'])
async def test_malformed_lifecycle_history_does_not_exhaust_future_launches(case, value):
    root, _, _, _, lifecycle, backend, run = case
    directory = root / 'runs/live/lifecycle'; directory.mkdir(parents=True, exist_ok=True)
    for index in range(1001):
        (directory / f'broken-{index}.json').write_text(value)
    run()
    assert (await lifecycle.launch_game('future-launch', 0))['state'] == 'COMPLETED'
    assert backend.launches == 1


async def test_abandonment_between_intent_and_dispatch_never_calls_native_submit(case, monkeypatch):
    _, store, reader, executor, _, _, run = case
    executor.pending, executor.input_pending = None, None
    executor._save()
    original = executor._save
    submitted = []
    async def action(*args): submitted.append(args); raise AssertionError('must not submit')
    reader.client = SimpleNamespace(action=action)
    def save_then_abandon():
        original()
        run()
    monkeypatch.setattr(executor, '_save', save_then_abandon)
    result = await executor.act('open_run_setup', {}, OBS, 'old-nav', 'Synthetic navigation', [])
    assert result['state'] == 'UNKNOWN' and not submitted
    assert store.checkpoint('executor', executor.registration.root)['pending'] is None


def test_newer_recovery_keeps_all_previous_tombstones(case):
    root, store, reader, _, _, _, run = case
    run()
    fresh = Executor(reader)
    fresh.pending = {'action': 'open_run_setup', 'parameters': {}, 'action_id': 'later-nav',
                     'observation_id': 'obs-0123456789abcdef-1', 'reason': 'Later synthetic intent', 'experience_refs': []}
    fresh._save()
    result = run('runs/checks/recovery-two.json')
    assert set(result['action_ids']) == {'old-nav', 'old-input', 'later-nav'}
    assert read_fence(store, root)['recovery_id'] == 'recovery-two'
