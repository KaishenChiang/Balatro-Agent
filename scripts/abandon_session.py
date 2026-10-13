"""Audited, retryable abandonment after normal process exit. No gameplay."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from balatro_agent.abandonment import SCHEMA, scope, fence_path, read_fence, collect_ids
from balatro_agent.installation_registry import InstallationRegistry, atomic_json, registry_path, CHECKPOINT_KEYS
from balatro_agent.local_audit import canonical, no_links, safe_path, make_dir
from balatro_agent.file_io import open_file
from balatro_agent.windows_game import WindowsGame


def wrapped(record):
    return {'schema': SCHEMA, 'record': record,
            'sha256': hashlib.sha256(canonical(record).encode()).hexdigest()}


def digest_bytes(path):
    no_links(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def run(root, *, output, apply=False, config=None, backend=None):
    root = root.absolute()
    target = safe_path(root, *Path(output).parts)
    if not target.is_relative_to(root / 'runs/checks') or target.suffix != '.json':
        raise ValueError('Recovery output must be a JSON file in runs/checks')
    recovery_id = target.stem
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', recovery_id):
        raise ValueError('Invalid recovery ID')
    config = config or Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'config.toml'
    store = InstallationRegistry(registry_path(config))
    backend = backend or WindowsGame(root / 'config/game-lifecycle.local.json')
    with store.lock():
        owner = store.read()
        if owner is None or Path(owner['root']) != root:
            raise ValueError('Installation owner must match this project before abandonment')
        if isinstance(backend, WindowsGame):
            from onboarding import verify_installation_entries
            verify_installation_entries(owner['installed_files'], Path(owner['steam_dir']),
                                        Path(owner['library_dir']), Path(owner['mods']))
        fence = read_fence(store, root)
        # New launcher windows resume the durable unfinished transaction; the
        # person never has to recover an old GUID from an error log.
        resumed = False
        if fence and fence['state'] == 'INTENT':
            recovery_id = fence['recovery_id']
            resumed = True
        else:
            candidates = []
            for candidate in (store.path.parent / 'abandoned-sessions' / scope(root)).glob('*/receipt.json'):
                proof = store.read_json(candidate, 16 * 1024 * 1024)
                if not isinstance(proof, dict):
                    raise ValueError('Invalid recovery archive; preserve it for inspection')
                record = proof.get('record', {})
                if not isinstance(record, dict):
                    raise ValueError('Invalid recovery archive; preserve it for inspection')
                if record.get('state') == 'INTENT' and record.get('root') == str(root) and proof == wrapped(record):
                    candidates.append(record['recovery_id'])
            if len(candidates) > 1:
                raise ValueError('Multiple unfinished recovery archives need inspection; all originals are preserved')
            if candidates:
                recovery_id = candidates[0]
                resumed = True
        archive = safe_path(store.path.parent, 'abandoned-sessions', scope(root), recovery_id)
        receipt = safe_path(archive, 'receipt.json')
        if receipt.exists():
            proof = store.read_json(receipt, 16 * 1024 * 1024)
            if not isinstance(proof, dict):
                raise ValueError('Invalid recovery receipt; preserve it')
            record = proof.get('record', {})
            if proof != wrapped(record) or record.get('root') != str(root) or (not resumed and record.get('output') != str(target)):
                raise ValueError('Recovery ID conflicts with its preserved receipt')
            if record.get('state') == 'COMMITTED':
                if apply and fence and fence['recovery_id'] == recovery_id and fence['state'] == 'INTENT':
                    atomic_json(fence_path(store, root), wrapped(record))
                result = {**record, 'duplicate': True}
                if apply:
                    atomic_json(target, result)
                return result  # Never abandon a later session with the old ID.
            if fence and fence['state'] == 'INTENT' and fence['recovery_id'] != recovery_id:
                raise ValueError('Pending recovery fence differs; preserve the archive')
        else:
            if fence and fence['state'] != 'COMMITTED':
                raise ValueError('Resume unfinished recovery ID: ' + fence['recovery_id'])
            if backend.find() is not None:
                raise ValueError('Balatro is still running; normally close its game window, then retry abandonment')
            paths = [store.path]
            checkpoints = []
            for area in CHECKPOINT_KEYS:
                local = root / 'runs/live' / area / 'checkpoint.json'
                mirror = store.checkpoint_path(area)
                checkpoints.extend([(local, area, False), (mirror, area, True)])
                paths.extend([local, mirror])
            # Preserve receipts independently of whether the damaged checkpoint
            # can still identify them. No game state or save is opened.
            lifecycle_paths = sorted((root / 'runs/live/lifecycle').glob('*.json'))
            lifecycle_paths += sorted((store.path.parent / 'lifecycle' / scope(root)).glob('*.json'))
            paths.extend(lifecycle_paths)
            paths = list(dict.fromkeys(paths))
            actions, operations, sessions = collect_ids([p for p, _, _ in checkpoints])
            history_operations = set()
            for path in lifecycle_paths:
                if path.stem != 'checkpoint' and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', path.stem):
                    history_operations.add(path.stem)
                try:
                    value = store.read_json(path, 65536)
                    value = value.get('record', value).get('receipt', {})
                    operation_id = value.get('operation_id')
                    if isinstance(operation_id, str):
                        history_operations.add(operation_id)
                        if value.get('state') in ('UNKNOWN', 'INTENT'):
                            operations.add(operation_id)
                except (ValueError, UnicodeError, AttributeError, TypeError):
                    # Invalid receipt types are archival material too. Their
                    # filenames are permanently reserved to prevent dispatch.
                    if path.stem != 'checkpoint' and path.stem in history_operations:
                        operations.add(path.stem)
                    continue
            for p, area, mirror in checkpoints:
                if area == 'lifecycle' and p.exists():
                    try:
                        cp = json.loads(p.read_bytes())
                        cp = cp.get('checkpoint', cp)
                        if isinstance(cp.get('pending'), str):
                            operations.add(cp['pending'])
                    except (ValueError, AttributeError, UnicodeError):
                        # Also fence orphan IDs in damaged lifecycle checkpoints.
                        for item in re.findall(rb'"pending"\s*:\s*"([A-Za-z0-9][A-Za-z0-9_.-]{0,79})"', p.read_bytes()):
                            operations.add(item.decode('ascii'))
            blocked_actions = set(actions)
            # With a missing/damaged executor intent, retain all previously used
            # IDs from the public action journal as permanent non-replay IDs.
            for log in sorted((root / 'runs/live/executor').glob('actions-*.jsonl')):
                no_links(log)
                with open_file(log, 'r', encoding='utf-8', errors='replace') as stream:
                    for line in stream:
                        try:
                            row = json.loads(line)
                            request = row.get('value', {}).get('request', {})
                            if row.get('kind') == 'intent' and isinstance(request.get('action_id'), str):
                                blocked_actions.add(request['action_id'])
                                obs = request.get('observation_id', '')
                                if re.fullmatch(r'obs-[a-f0-9]{16}-[0-9]+', obs):
                                    sessions.add(obs.split('-')[1])
                        except (ValueError, AttributeError, TypeError):
                            continue
            for key, values in [('action_ids', actions), ('blocked_action_ids', blocked_actions), ('operation_ids', operations), ('history_operation_ids', history_operations), ('sessions', sessions)]:
                values.update(fence[key] if fence else [])
            if not apply:
                return {'schema': SCHEMA, 'state': 'PLANNED', 'recovery_id': recovery_id,
                        'safe_to_prepare': False, 'game_action_submitted': False,
                        'action_ids': sorted(actions), 'operation_ids': sorted(operations)}
            make_dir(archive)
            saved = []
            for index, path in enumerate(paths):
                original = digest_bytes(path)
                backup = safe_path(archive, str(index) + '.bin')
                if original is not None:
                    data = path.read_bytes()
                    if not backup.exists():
                        with open_file(backup, 'xb') as stream:
                            stream.write(data); stream.flush(); os.fsync(stream.fileno())
                    if digest_bytes(backup) != original or hashlib.sha256(data).hexdigest() != original:
                        raise ValueError('Archive verification failed; preserve the original files')
                saved.append({'path': str(path), 'backup': backup.name, 'sha256': original})
            record = {'schema': SCHEMA, 'root': str(root), 'output': str(target), 'recovery_id': recovery_id,
                      'utc': datetime.now(timezone.utc).isoformat(), 'state': 'INTENT',
                      'original_action_state': 'UNKNOWN', 'game_action_submitted': False,
                      'normal_game_completed': False, 'safe_to_prepare': False,
                      'action_ids': sorted(actions), 'blocked_action_ids': sorted(blocked_actions),
                      'operation_ids': sorted(operations), 'history_operation_ids': sorted(history_operations),
                      'sessions': sorted(sessions), 'files': saved,
                      'checkpoints': [{'path': str(p), 'area': a, 'mirror': m} for p, a, m in checkpoints]}
            if backend.find() is not None or any(digest_bytes(Path(item['path'])) != item['sha256'] for item in saved):
                raise ValueError('State changed during abandonment; retry after normal exit')
            atomic_json(receipt, wrapped(record))
            atomic_json(fence_path(store, root), wrapped(record))
        if not apply:
            return {**record, 'safe_to_prepare': False}
        # Resume after any prefix of writes; only original bytes or our exact
        # cleared bytes are accepted. Archive and fence always precede release.
        if backend.find() is not None:
            raise ValueError('Balatro is still running; normally close its game window, then resume the same recovery ID')
        checkpoints = {item['path']: item for item in record['checkpoints']}
        for item in record['files']:
            backup = safe_path(archive, item['backup'])
            if digest_bytes(backup) != item['sha256']:
                raise ValueError('Preserved recovery backup changed')
            actual = digest_bytes(Path(item['path']))
            if actual == item['sha256']:
                continue
            cp = checkpoints.get(item['path'])
            empty = {key: None for key in CHECKPOINT_KEYS[cp['area']]} if cp else None
            cleared = {'schema': 'checkpoint-mirror-v1', 'root': str(root), 'checkpoint': empty} if cp and cp['mirror'] else empty
            if cp is None or actual != hashlib.sha256(canonical(cleared).encode()).hexdigest():
                raise ValueError('State changed after recovery intent; preserve the archive')
        if backend.find() is not None:
            raise ValueError('Balatro appeared during recovery; normally close it and resume the same recovery ID')
        # An interrupted first fence write can be repaired only after verifying
        # all original/cleared bytes and backups under the same process lock.
        if not fence or fence['recovery_id'] != recovery_id:
            atomic_json(fence_path(store, root), wrapped(record))
        for cp in record['checkpoints']:
            empty = {key: None for key in CHECKPOINT_KEYS[cp['area']]}
            cleared = {'schema': 'checkpoint-mirror-v1', 'root': str(root), 'checkpoint': empty} if cp['mirror'] else empty
            atomic_json(Path(cp['path']), cleared)
        if backend.find() is not None:
            raise ValueError('Balatro appeared during recovery; normally close it and resume abandonment')
        record = {**record, 'state': 'COMMITTED', 'safe_to_prepare': True}
        atomic_json(receipt, wrapped(record))
        atomic_json(fence_path(store, root), wrapped(record))
        result = {**record, 'duplicate': False}
        atomic_json(target, result)
        return result
