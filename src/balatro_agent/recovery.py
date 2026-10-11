"""Explicit retirement of a demonstrably lost game session; never resubmit.

Retirement ends only the local waiting barrier. The archived action remains
UNKNOWN, and an interrupted game never becomes a normal completed game.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import uuid
from .file_io import open_file, replace_file

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from .local_audit import LocalAudit, canonical, make_dir, safe_path
from .transport import ReaderError

ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}')
ACTION_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}')
OBS = re.compile(r'obs-([a-f0-9]{16})-[0-9]+')


class RetirementResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    state: Literal['RETIRED']
    reason: Literal['lost_session_archived']
    recovery_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$')
    action_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$')
    original_action_state: Literal['UNKNOWN']
    old_session: str = Field(pattern=r'^[a-f0-9]{16}$')
    current_session: str = Field(pattern=r'^[a-f0-9]{16}$')
    submitted: Literal[False]
    game_action_submitted: Literal[False]
    read_only: Literal[False]
    normal_game_completed: Literal[False]
    duplicate: bool
    write_state: Literal['COMMITTED']


class SessionRecovery:
    def __init__(self, executor):
        self.executor = executor
        self.reader = executor.reader
        self.root = executor.root / 'retired-sessions'
        self.audit = LocalAudit(self.reader.settings, activity=getattr(self.reader, 'activity', None))

    def _reply(self, response):
        return self.audit.deliver('recover_lost_session', response, write=True)

    def _reject(self, reason, recovery_id=None):
        return self._reply({'state': 'REJECTED', 'reason': reason,
                            'recovery_id': recovery_id, 'submitted': False,
                            'game_action_submitted': False, 'read_only': False,
                            'write_state': 'NOT_COMMITTED'})

    def _archive(self, path, record):
        make_dir(self.root)
        temp = safe_path(self.root, uuid.uuid4().hex + '.tmp')
        with open_file(temp, 'x', encoding='utf-8') as stream:
            stream.write(canonical(record)); stream.flush(); os.fsync(stream.fileno())
        replace_file(temp, path)

    def _missing_status_history(self, action_id, current_session):
        """Find a delivered missing-record status, never infer non-submission.

        Host failures can leave no local intent. Their old session is usable
        only when this service durably delivered the original status there.
        A same-session absence, intent, terminal result or ambiguous history
        cannot authorize retirement. Return bounded public status fields only.
        """
        paths = list(self.executor.root.glob('actions-*.jsonl'))
        if len(paths) > 100:
            raise ValueError('history_limit')
        total, sessions = 0, {}
        for item in paths:
            if not re.fullmatch(r'actions-[a-f0-9]{32}\.jsonl', item.name):
                raise ValueError('invalid_history')
            path = safe_path(self.executor.root, item.name)
            size = path.stat().st_size
            total += size
            if size > 16 * 1024 * 1024 or total > 32 * 1024 * 1024:
                raise ValueError('history_limit')
            with open_file(path, 'r', encoding='utf-8') as stream:
                for line in stream:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError('invalid_history')
                    if row.get('client_context') != self.reader.settings.client_context:
                        continue
                    value = row.get('value')
                    if not isinstance(value, dict):
                        continue
                    request = value.get('request')
                    if (row.get('kind') == 'intent' and isinstance(request, dict)
                            and request.get('action_id') == action_id):
                        return None
                    if value.get('action_id') != action_id:
                        continue
                    if (value.get('state') in ('RUNNING', 'AWAITING_INPUT', 'COMPLETED', 'REJECTED', 'RETIRED')
                            or value.get('submitted') is True):
                        return None
                    session = value.get('game_session')
                    if (row.get('kind') != 'delivered_action_status'
                            or value.get('state') != 'UNKNOWN'
                            or value.get('reason') != 'record_not_found'
                            or value.get('read_only') is not True
                            or value.get('callback_confirmed') is not False
                            or value.get('related_events_complete') is not False
                            or (value.get('submitted') is not None and value.get('submitted') is not False)
                            or not isinstance(session, str)
                            or not re.fullmatch(r'[a-f0-9]{16}', session)
                            or session == current_session):
                        continue
                    sessions[session] = {'action_id': action_id, 'state': 'UNKNOWN',
                                         'reason': 'record_not_found', 'game_session': session,
                                         'read_only': True, 'submitted': value.get('submitted'),
                                         'callback_confirmed': False, 'related_events_complete': False}
        return next(iter(sessions.values())) if len(sessions) == 1 else None

    async def recover(self, action_id, observation_id, recovery_id):
        if not (isinstance(action_id, str) and ACTION_ID.fullmatch(action_id)
                and isinstance(observation_id, str) and OBS.fullmatch(observation_id)
                and isinstance(recovery_id, str) and ID.fullmatch(recovery_id)):
            return self._reject('invalid_request')
        if self.reader._tool_lock.locked():
            return self._reject('action_busy', recovery_id)
        async with self.reader._tool_lock:
            exe = self.executor
            request = {'action_id': action_id, 'observation_id': observation_id,
                       'recovery_id': recovery_id}
            try:
                if exe.checkpoint_broken:
                    return self._reject('checkpoint_unavailable', recovery_id)
                lifecycle = getattr(exe, 'lifecycle', None)
                if lifecycle is not None and lifecycle.blocks_actions():
                    return self._reject('operation_busy', recovery_id)
                exe.registration.check()
                path = safe_path(self.root, recovery_id + '.json')
                previous = None
                if path.exists():
                    if path.stat().st_size > 65536:
                        raise ValueError('invalid_receipt')
                    previous = json.loads(path.read_text(encoding='utf-8'))
                    if previous.get('request') != request:
                        return self._reject('id_conflict', recovery_id)
                    expected = previous.get('checkpoint_before')
                    response = RetirementResponse.model_validate(previous.get('response')).model_dump()
                    if (not isinstance(expected, dict)
                            or response.get('action_id') != action_id
                            or response.get('recovery_id') != recovery_id
                            or response.get('current_session') != OBS.fullmatch(observation_id)[1]
                            or response.get('old_session') == response.get('current_session')
                            or previous.get('checkpoint_sha256') != hashlib.sha256(canonical(expected).encode()).hexdigest()):
                        raise ValueError('invalid_receipt')
                    if exe.pending is None and exe.input_pending is None:
                        return self._reply({**response, 'duplicate': True})
                if exe.pending and exe.pending['action_id'] != action_id:
                    return self._reject('pending_action_mismatch', recovery_id)
                current_session = OBS.fullmatch(observation_id)[1]
                status_history = None
                if exe.pending:
                    old_session = exe.pending['observation_id'].split('-')[1]
                else:
                    if exe.input_pending is not None:
                        return self._reject('pending_action_mismatch', recovery_id)
                    status_history = self._missing_status_history(action_id, current_session)
                    if status_history is None:
                        return self._reject('pending_action_mismatch', recovery_id)
                    old_session = status_history['game_session']
                before = {'pending': exe.pending, 'input_pending': exe.input_pending}
                if previous is not None and before != previous['checkpoint_before']:
                    return self._reject('checkpoint_changed', recovery_id)
                # A local file edit cannot silently release the in-memory gate.
                checkpoint = safe_path(exe.root, 'checkpoint.json')
                if json.loads(checkpoint.read_text(encoding='utf-8')) != before:
                    return self._reject('checkpoint_changed', recovery_id)
                if old_session == current_session:
                    return self._reject('session_not_lost', recovery_id)
                status = await exe._query(action_id)  # Query only, no act_submit.
                if (status.get('game_session') != current_session
                        or status.get('state') != 'UNKNOWN'
                        or status.get('action_id') != action_id
                        or status.get('reason') != 'record_not_found'):
                    return self._reject('session_loss_unconfirmed', recovery_id)
                latest = await self.reader._observe()
                observation = latest.get('observation', {})
                if latest.get('status') != 'ok':
                    return self._reject('observation_unavailable', recovery_id)
                if type(observation.get('profile')) is not int or observation['profile'] not in (1, 2, 3):
                    return self._reject('unknown_profile', recovery_id)
                if observation.get('observation_id') != observation_id:
                    return self._reject('stale_observation', recovery_id)
                if not observation.get('ready'):
                    return self._reject('not_ready', recovery_id)
                response = {'state': 'RETIRED', 'reason': 'lost_session_archived',
                            'recovery_id': recovery_id, 'action_id': action_id,
                            'original_action_state': 'UNKNOWN', 'old_session': old_session,
                            'current_session': current_session, 'submitted': False,
                            'game_action_submitted': False, 'read_only': False,
                            'normal_game_completed': False, 'duplicate': False,
                            'write_state': 'COMMITTED'}
                record = {'evidence_type': 'explicit_lost_session_retirement',
                          'utc': datetime.now(timezone.utc).isoformat(), 'request': request,
                          'checkpoint_before': before,
                          'checkpoint_sha256': hashlib.sha256(canonical(before).encode()).hexdigest(),
                          'retirement_basis': 'pending_intent' if exe.pending else 'delivered_status_history',
                          'original_status_history': status_history,
                          'queried_status': status, 'current_observation': observation,
                          'response': response}
                if previous is None:
                    # Retain both parent and input intent before removing the barrier.
                    self._archive(path, record)
                exe._record('lost_session_retirement', response)
                exe.pending, exe.input_pending = None, None
                try:
                    exe._save()
                except OSError:
                    exe.pending, exe.input_pending = before['pending'], before['input_pending']
                    raise
                # A lost response is recovered using the durable same-ID receipt.
                return self._reply(response)
            except ReaderError:
                return self._reject('transport_uncertain', recovery_id)
            except (OSError, ValueError, KeyError, TypeError):
                return self._reject('journal_unavailable', recovery_id)
            except Exception:
                return self._reject('service_error', recovery_id)

