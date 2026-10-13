"""Explicit end of a stopped session. Preserve uncertainty and never replay."""
import hashlib
import json
import os
import re
from pathlib import Path

from .local_audit import canonical, no_links, safe_path

SCHEMA = 'abandon-session-1'


def scope(root):
    return hashlib.sha256(os.path.normcase(str(root.absolute())).encode()).hexdigest()[:16]


def fence_path(store, root):
    return safe_path(store.path.parent, 'session-fences', scope(root) + '.json')


def read_fence(store, root):
    path = fence_path(store, root)
    if not path.exists():
        return None
    value = store.read_json(path, 16 * 1024 * 1024)
    if not isinstance(value, dict) or not isinstance(value.get('record'), dict):
        raise ValueError('Invalid session abandonment fence; preserve it')
    record = value.get('record', {})
    if (value.get('schema') != SCHEMA or record.get('root') != str(root)
            or record.get('state') not in ('INTENT', 'COMMITTED')
            or not isinstance(record.get('recovery_id'), str)
            or value.get('sha256') != hashlib.sha256(canonical(record).encode()).hexdigest()
            or any(not isinstance(record.get(k), list) or any(not isinstance(v, str) for v in record[k])
                   for k in ('action_ids', 'blocked_action_ids', 'operation_ids', 'history_operation_ids', 'sessions'))):
        raise ValueError('Invalid session abandonment fence; preserve it')
    archive = safe_path(store.path.parent, 'abandoned-sessions', scope(root), record['recovery_id'], 'receipt.json')
    proof = store.read_json(archive, 16 * 1024 * 1024)
    if not isinstance(proof, dict) or not isinstance(proof.get('record'), dict):
        raise ValueError('Invalid session abandonment receipt; preserve it')
    # The committed receipt may precede the fence update after a crash.
    if proof.get('sha256') != hashlib.sha256(canonical(proof.get('record')).encode()).hexdigest():
        raise ValueError('Invalid session abandonment receipt; preserve it')
    expected = {**proof.get('record', {}), 'state': record['state'], 'safe_to_prepare': record['state'] == 'COMMITTED'}
    if expected != record:
        raise ValueError('Session abandonment archive differs; preserve it')
    return record


def generation(record):
    return (record['recovery_id'], record['state']) if record else None


def retired_action(record, action_id):
    if record and action_id in record['action_ids']:
        return {'state': 'UNKNOWN', 'reason': 'session_abandoned', 'action_id': action_id,
                'submitted': None, 'read_only': True, 'retired': True,
                'original_action_state': 'UNKNOWN', 'normal_game_completed': False}
    return None


def collect_ids(paths):
    """Extract identifiers only from archived public intents, never save data."""
    actions, operations, sessions = set(), set(), set()
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'action_id' and isinstance(item, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}', item):
                    actions.add(item)
                if key == 'operation_id' and isinstance(item, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', item):
                    operations.add(item)
                if key == 'observation_id' and isinstance(item, str):
                    match = re.fullmatch(r'obs-([a-f0-9]{16})-[0-9]+', item)
                    if match:
                        sessions.add(match[1])
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    for path in paths:
        if not path.exists():
            continue
        no_links(path)
        try:
            walk(json.loads(path.read_bytes()))
        except (ValueError, UnicodeError):
            # A damaged checkpoint is still archived byte for byte. Recover
            # identifier tokens conservatively without pretending to parse it.
            text = path.read_bytes().decode('utf-8', errors='replace')
            for key, item in re.findall(r'"(action_id|operation_id|observation_id)"\s*:\s*"([^"\r\n]*)"', text):
                walk({key: item})
    return actions, operations, sessions
