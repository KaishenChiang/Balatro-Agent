"""Normal OS lifecycle with durable receipts; never a game recovery shortcut."""
import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Literal
import uuid
from .file_io import open_file, replace_file

from pydantic import BaseModel, ConfigDict, Field

from .local_audit import LocalAudit, canonical, make_dir, safe_path
from .transport import ReaderError
from .windows_game import GameProcessError, ProcessIdentity, WindowsGame
from .installation_registry import RegistrationGuard

ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}')
OBS = re.compile(r'obs-[a-f0-9]{16}-[0-9]+')
Reason = Literal['already_running', 'started', 'closed', 'already_stopped',
                 'operation_busy', 'game_action_unknown', 'checkpoint_unavailable',
                 'invalid_request', 'id_conflict', 'installation_unverified',
                 'windows_only', 'process_unverified', 'multiple_game_processes',
                 'game_window_unverified', 'process_changed', 'close_dispatch_failed',
                 'test_profile_required', 'unknown_profile', 'observation_unavailable', 'stale_observation',
                 'unsafe_to_close', 'journal_unavailable', 'launch_timeout',
                 'close_timeout', 'dispatch_uncertain', 'service_error', 'receipt_limit']


class Receipt(BaseModel):
    model_config = ConfigDict(extra='forbid')
    operation_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$')
    tool: Literal['launch_game', 'close_game']
    state: Literal['INTENT', 'COMPLETED', 'REJECTED', 'UNKNOWN']
    reason: Reason
    submitted: bool | None = False
    running: bool | None = None
    mcp_connected: bool | None = None
    focus: Literal['confirmed', 'not_confirmed', 'not_requested'] = 'not_requested'
    read_only: bool = False


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    receipt: Receipt
    target_pid: int | None = Field(default=None, gt=0, le=4294967295)
    target_created: int | None = Field(default=None, gt=0, le=18446744073709551615)


class LifecycleJournal:
    def __init__(self, settings):
        self.root = settings.log_dir / 'lifecycle'
        self.registration = RegistrationGuard(settings)
        self._expected_checkpoint = None

    def _read(self, path):
        if path.stat().st_size > 8192:
            raise ValueError('invalid_checkpoint')
        return json.loads(path.read_text(encoding='utf-8'))

    def pending(self):
        self.restore_pending()
        self.registration.check()
        path = safe_path(self.root, 'checkpoint.json')
        if not path.exists():
            self._expected_checkpoint = {'pending': None}
            return None
        value = self._read(path)
        if set(value) != {'pending'} or value['pending'] is not None and (not isinstance(value['pending'], str) or not ID.fullmatch(value['pending'])):
            raise ValueError('invalid_checkpoint')
        self._expected_checkpoint = value
        return value['pending']

    def _atomic(self, path, value):
        make_dir(self.root)
        temp = safe_path(self.root, uuid.uuid4().hex + '.tmp')
        with open_file(temp, 'x', encoding='utf-8') as stream:
            stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
        replace_file(temp, path)

    def set_pending(self, value):
        checkpoint = {'pending': value}
        self.registration.persist('lifecycle', checkpoint,
                                  lambda: self._atomic(safe_path(self.root, 'checkpoint.json'), checkpoint),
                                  expected=self._expected_checkpoint)
        self._expected_checkpoint = dict(checkpoint)

    def read(self, operation_id):
        self.restore_pending()
        path = safe_path(self.root, operation_id + '.json')
        if not path.exists():
            store = self.registration.store
            if store is None:
                return None
            with store.lock():
                self.registration._check()
                record = self._independent_record(operation_id)
                if record is None:
                    return None
                self._atomic(path, record.model_dump())
        record = Record.model_validate(self._read(path))
        if record.receipt.operation_id != operation_id:
            raise ValueError('invalid_receipt')
        return record

    def save(self, record):
        store = self.registration.store
        if store is None:
            return self._atomic(safe_path(self.root, record.receipt.operation_id + '.json'), record.model_dump())
        with store.lock():
            self.registration._check()
            value = record.model_dump()
            # Retain the receipt outside the replaceable source directory before
            # local persistence. A checkpoint ID alone cannot recover a query.
            from .installation_registry import atomic_json
            atomic_json(self._independent_path(record.receipt.operation_id), {
                'schema': 'lifecycle-receipt-mirror-v1', 'root': str(self.registration.root),
                'record': value, 'sha256': hashlib.sha256(canonical(value).encode()).hexdigest()})
            self._atomic(safe_path(self.root, record.receipt.operation_id + '.json'), value)

    def _independent_path(self, operation_id, *, directory='lifecycle'):
        if not isinstance(operation_id, str) or not ID.fullmatch(operation_id):
            raise ValueError('invalid_receipt')
        scope = hashlib.sha256(os.path.normcase(str(self.registration.root)).encode()).hexdigest()[:16]
        return safe_path(self.registration.store.path.parent, directory, scope, operation_id + '.json')

    def retired(self, operation_id):
        """Read a separately authorized lost-receipt tombstone; never create one."""
        store = self.registration.store
        if store is None:
            return False
        with store.lock():
            owner = store.read()
            if owner is None or Path(owner['root']) != self.registration.root:
                raise ValueError('registration_owner_changed')
            from .abandonment import read_fence
            fence = read_fence(store, self.registration.root)
            if fence and fence['state'] == 'COMMITTED' and operation_id in fence['operation_ids']:
                return True
            path = self._independent_path(operation_id, directory='retired-lifecycle')
            if not path.exists():
                return False
            self.registration._check()
            value = store.read_json(path, 16384)
            record = value.get('record')
            if (not isinstance(record, dict)
                    or value.get('schema') != 'manual-orphan-lifecycle-retirement-v1'
                    or not isinstance(record.get('root'), str) or Path(record['root']) != self.registration.root
                    or record.get('operation_id') != operation_id
                    or record.get('original_operation_state') != 'UNKNOWN'
                    or record.get('original_submission') is not None
                    or record.get('game_action_submitted') is not False
                    or record.get('normal_game_completed') is not False
                    or value.get('sha256') != hashlib.sha256(canonical(record).encode()).hexdigest()):
                raise ValueError('invalid_lifecycle_retirement')
            return True

    def _independent_record(self, operation_id):
        store = self.registration.store
        if store is None:
            return None
        owner = store.read()
        if owner is None or Path(owner['root']) != self.registration.root:
            raise ValueError('registration_owner_changed')
        path = self._independent_path(operation_id)
        if not path.exists():
            return None
        value = store.read_json(path, 16384)
        record = Record.model_validate(value['record'])
        if (value.get('schema') != 'lifecycle-receipt-mirror-v1'
                or not isinstance(value.get('root'), str) or Path(value['root']) != self.registration.root
                or record.receipt.operation_id != operation_id
                or value.get('sha256') != hashlib.sha256(canonical(value['record']).encode()).hexdigest()):
            raise ValueError('invalid_independent_lifecycle_receipt')
        return record

    def restore_pending(self):
        """Restore missing local mirrors; never infer completion or dispatch."""
        store = self.registration.store
        if store is None:
            return
        with store.lock():
            self._restore_pending_locked()

    def _restore_pending_locked(self):
        store = self.registration.store
        owner = store.read()
        if owner is None or Path(owner['root']) != self.registration.root:
            raise ValueError('registration_owner_changed')
        pending = store.checkpoint('lifecycle', self.registration.root)
        operation_id = pending['pending']
        if operation_id is None:
            return
        self._independent_path(operation_id)  # Validate before any local path use.
        checkpoint = safe_path(self.root, 'checkpoint.json')
        receipt_path = safe_path(self.root, operation_id + '.json')
        if checkpoint.exists() and receipt_path.exists():
            return
        # Do not rebuild, erase or bypass a game-action checkpoint.
        mirrored = store.checkpoint('executor', self.registration.root)
        executor_path = safe_path(self.registration.log_dir, 'executor', 'checkpoint.json')
        local = store.read_json(executor_path, 65536) if executor_path.exists() else {'pending': None, 'input_pending': None}
        if local != mirrored:
            raise ValueError('independent_checkpoint_differs')
        record = self._independent_record(operation_id)
        if record is None:
            return  # Legacy ID-only mirror remains protected and unresolved.
        if checkpoint.exists() and self._read(checkpoint) != pending:
            raise ValueError('independent_checkpoint_differs')
        if receipt_path.exists() and self._read(receipt_path) != record.model_dump():
            raise ValueError('independent_lifecycle_receipt_differs')
        if not receipt_path.exists():
            self._atomic(receipt_path, record.model_dump())
        if not checkpoint.exists():
            self._atomic(checkpoint, pending)


class GameLifecycle:
    def __init__(self, reader, executor, backend=None, *, poll_s=0.2):
        self.reader, self.executor = reader, executor
        self.backend = backend or WindowsGame(reader.settings.lifecycle_file)
        self.journal = LifecycleJournal(reader.settings)
        self.audit = LocalAudit(reader.settings, activity=reader.activity)
        self.activity_window = None
        self.activity_operation_id = None
        self.poll_s = poll_s

    def blocks_actions(self):
        try:
            return self.journal.pending() is not None
        except (OSError, ValueError):
            return True

    def _deliver(self, receipt, duplicate=False):
        result = receipt.model_dump()
        result['duplicate'] = duplicate
        if (receipt.tool == 'launch_game' and not duplicate
                and receipt.operation_id == self.activity_operation_id and self.activity_window is not None):
            result['activity_window'] = self.activity_window
        try:
            self.audit.record(receipt.tool, 'delivered', result)
        except (OSError, ValueError):
            result.update(state='UNKNOWN' if receipt.submitted is not False else 'REJECTED', reason='journal_unavailable')
            self.reader.activity.delivered(receipt.tool, result)
        return result

    def _show_activity(self, operation_id):
        # Fake/development backends never open a desktop window.
        if not isinstance(self.backend, WindowsGame):
            return
        self.activity_operation_id = operation_id
        try:
            from .activity import open_viewer
            self.activity_window = open_viewer(self.reader.settings)
        except Exception:
            self.activity_window = 'unavailable'

    async def launch_game(self, operation_id, timeout_s=25.0):
        return await self._request('launch_game', operation_id, None, timeout_s)

    async def close_game(self, operation_id, observation_id, timeout_s=15.0):
        return await self._request('close_game', operation_id, observation_id, timeout_s)

    async def _connected(self):
        try:
            await self.reader._envelope('health')
            return True
        except ReaderError:
            return False

    def _finish(self, record):
        try:
            self.journal.save(record)
            if record.receipt.state in ('COMPLETED', 'REJECTED') and self.journal.pending() == record.receipt.operation_id:
                self.journal.set_pending(None)
        except (OSError, ValueError):
            record.receipt.state = 'UNKNOWN' if record.receipt.submitted or self.blocks_actions() else 'REJECTED'
            record.receipt.reason = 'journal_unavailable'
        return self._deliver(record.receipt)

    def _focus(self, process):
        try:
            return 'confirmed' if self.backend.focus(process) else 'not_confirmed'
        except GameProcessError:
            # A running process and connected Mod are sufficient startup proof.
            # Window/focus failures are reported separately, not force-bypassed.
            return 'not_confirmed'

    async def _wait(self, record, timeout_s):
        deadline = time.monotonic() + timeout_s
        receipt = record.receipt
        while True:
            process = self.backend.find()
            receipt.running = process is not None
            if receipt.tool == 'launch_game':
                receipt.mcp_connected = process is not None and await self._connected()
                if receipt.mcp_connected:
                    receipt.focus = self._focus(process)
                    receipt.state, receipt.reason = 'COMPLETED', 'started'
                    return self._finish(record)
            else:
                target = ProcessIdentity(record.target_pid, record.target_created)
                if process is None:
                    receipt.state, receipt.reason = 'COMPLETED', 'closed'
                    receipt.mcp_connected = False
                    return self._finish(record)
                if process != target:
                    # The original process exited; another one appeared. Never
                    # close it or claim that the game is currently stopped.
                    receipt.state, receipt.reason = 'UNKNOWN', 'process_changed'
                    return self._finish(record)
            if time.monotonic() >= deadline:
                receipt.state = 'UNKNOWN'
                receipt.reason = 'launch_timeout' if receipt.tool == 'launch_game' else 'close_timeout'
                return self._finish(record)
            await asyncio.sleep(min(self.poll_s, max(0, deadline - time.monotonic())))

    async def _request(self, tool, operation_id, observation_id, timeout_s):
        valid_id = isinstance(operation_id, str) and ID.fullmatch(operation_id)
        if valid_id and (operation_id.casefold() == 'checkpoint' or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])', operation_id.split('.')[0])):
            valid_id = False
        receipt = Receipt(operation_id=operation_id if valid_id else 'invalid', tool=tool,
                          state='REJECTED', reason='invalid_request')
        if (not valid_id or isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float))
                or not math.isfinite(timeout_s) or not 0 <= timeout_s <= 30
                or tool == 'close_game' and (not isinstance(observation_id, str) or not OBS.fullmatch(observation_id))):
            return self._deliver(receipt)
        fingerprint = hashlib.sha256(canonical({'tool': tool, 'observation_id': observation_id,
                                                'timeout_s': float(timeout_s)}).encode()).hexdigest()
        if self.reader._tool_lock.locked():
            receipt.reason = 'operation_busy'
            return self._deliver(receipt)
        async with self.reader._tool_lock:
            record = None
            try:
                self.executor.refresh_abandonment()
                if self.journal.retired(operation_id):
                    receipt.state, receipt.reason = 'UNKNOWN', 'dispatch_uncertain'
                    receipt.submitted, receipt.read_only = None, True
                    result = self._deliver(receipt, True)
                    result['retired'] = True
                    return result
                saved = self.journal.read(operation_id)
                pending = self.journal.pending()
                if saved:
                    if saved.fingerprint != fingerprint:
                        receipt.reason = 'id_conflict'
                        return self._deliver(receipt)
                    if saved.receipt.state in ('COMPLETED', 'REJECTED'):
                        if pending == operation_id:
                            self.journal.set_pending(None)
                        return self._deliver(saved.receipt, True)
                    if pending != operation_id:
                        receipt.reason = 'checkpoint_unavailable'
                        return self._deliver(receipt)
                    # Query/poll only. INTENT can be a crash before dispatch:
                    # absence cannot prove it is safe to resend.
                    saved.receipt.state, saved.receipt.submitted = 'UNKNOWN', None
                    record = saved
                    receipt = saved.receipt
                    return await self._wait(saved, timeout_s)
                if pending:
                    receipt.reason = 'operation_busy'
                    return self._deliver(receipt)
                if self.executor.checkpoint_broken:
                    receipt.reason = 'checkpoint_unavailable'
                    return self._deliver(receipt)
                from .abandonment import read_fence
                store = self.journal.registration.store
                fence = read_fence(store, self.journal.registration.root) if store else None
                retired_ids = set(fence['operation_ids'] + fence['history_operation_ids']) if fence else set()
                if sum(p.stem not in retired_ids for p in self.journal.root.glob('*.json')) >= 1000:
                    receipt.reason = 'receipt_limit'
                    return self._deliver(receipt)
                process = self.backend.find()
                record = Record(fingerprint=fingerprint, receipt=receipt)
                if tool == 'launch_game' and process:
                    self.audit.record(tool, 'existing_window_intent', {'operation_id':operation_id})
                    self._show_activity(operation_id)
                    receipt.state, receipt.reason, receipt.running = 'COMPLETED', 'already_running', True
                    receipt.mcp_connected = await self._connected()
                    receipt.focus = self._focus(process)
                    return self._finish(record)
                if self.executor.pending:
                    receipt.reason = 'game_action_unknown'
                    return self._finish(record)
                if tool == 'close_game':
                    if process is None:
                        receipt.state, receipt.reason, receipt.running = 'COMPLETED', 'already_stopped', False
                        return self._finish(record)
                    try:
                        result = await self.reader._observe()
                    except ReaderError:
                        receipt.reason = 'observation_unavailable'
                        return self._finish(record)
                    obs = result.get('observation', {})
                    if result.get('status') != 'ok' or type(obs.get('profile')) is not int or obs['profile'] not in (1, 2, 3):
                        receipt.reason = 'observation_unavailable'
                        return self._finish(record)
                    if obs.get('observation_id') != observation_id:
                        receipt.reason = 'stale_observation'
                        return self._finish(record)
                    safe = obs.get('phase') == 'terminal' and obs.get('outcome') in ('win', 'loss') or (
                        obs.get('phase') == 'main_menu' and obs.get('resources', {}).get('availability') == 'not_applicable')
                    if not obs.get('ready') or not safe:
                        receipt.reason = 'unsafe_to_close'
                        return self._finish(record)
                    record.target_pid, record.target_created = process.pid, process.created
                # Write both checkpoint and intent before issuing any launch or
                # close request. Failures after dispatch remain query-only.
                receipt.state, receipt.reason = 'INTENT', 'dispatch_uncertain'
                self.journal.save(record)
                self.journal.set_pending(operation_id)
                self.audit.record(tool, 'intent', receipt.model_dump())
                if tool == 'launch_game':
                    self._show_activity(operation_id)
                    with self.journal.registration.dispatch():
                        self.backend.launch()
                else:
                    with self.journal.registration.dispatch():
                        self.backend.close(process)
                receipt.submitted = True
                self.journal.save(record)
                return await self._wait(record, timeout_s)
            except GameProcessError as exc:
                # Explicit backend rejection precedes its native dispatch.
                receipt.state, receipt.reason = 'REJECTED', exc.code
                if record and receipt.submitted is not False:
                    receipt.state = 'UNKNOWN'
                if record:
                    return self._finish(record)
                return self._deliver(receipt)
            except (OSError, ValueError, TypeError):
                receipt.state = 'UNKNOWN' if record and self.blocks_actions() else 'REJECTED'
                receipt.reason = 'journal_unavailable'
                return self._deliver(receipt)
            except Exception:
                receipt.state = 'UNKNOWN' if record and self.blocks_actions() else 'REJECTED'
                receipt.reason = 'service_error'
                return self._deliver(receipt)
