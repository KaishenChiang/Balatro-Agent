"""Atomic current experience files; isolated TEST revisions; no strategy content."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from .file_io import open_file, replace_file
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .local_audit import LocalAudit, canonical, make_dir, safe_path

LIMIT_NOTES = 200
LIMIT_REVISIONS = 100
LIMIT_FILE_BYTES = 65536
LIMIT_RESPONSE_BYTES = 262144
ID = re.compile(r'^(EXP|TEST)-[A-Z0-9][A-Z0-9-]{0,47}$')
WRITE_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$')
ERRORS = {
    'invalid_input': 'The note request structure, ID, kind or text does not meet the bounded contract.',
    'not_found': 'The requested note or revision does not exist.',
    'revision_conflict': 'Expected revision differs from the current revision on disk.',
    'migration_required': 'Legacy local experience must be archived and migrated before writing.',
    'id_conflict': 'This write ID already belongs to different content.',
    'resource_limit': 'Note count, history or response size exceeds limits.',
    'unsafe_path': 'The controlled directory contains an unsupported link or path structure.',
    'store_corrupt': 'Note storage failed its integrity checks.',
    'busy': 'Another note write is active or retains a lock; this request was not committed.',
    'storage_unavailable': 'Controlled note storage is unavailable; this request was not committed.',
    'log_unavailable': 'The safe intent could not be recorded; the note was not committed.',
}


class NoteError(Exception):
    pass


class Source(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    run_id: str = Field(pattern=r'^(n5|test)-[A-Za-z0-9-]{1,60}$')
    steps: list[int] = Field(min_length=1, max_length=50)

    @model_validator(mode='after')
    def bounded(self):
        if any(type(n) is not int or not 1 <= n <= 5000 for n in self.steps) or len(set(self.steps)) != len(self.steps):
            raise ValueError('invalid_input')
        self.steps = sorted(self.steps)
        return self


class NoteContent(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    sources: list[Source] = Field(min_length=1, max_length=20)
    facts: list[str] = Field(min_length=1, max_length=20)
    interpretation: list[str] = Field(min_length=1, max_length=20)
    conditions: list[str] = Field(min_length=1, max_length=20)
    counterexamples: list[str] = Field(min_length=1, max_length=20)
    confidence: str = Field(pattern=r'^(low|medium|high)$')
    revision_reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def bounded_text(self):
        texts = self.facts + self.interpretation + self.conditions + self.counterexamples + [self.revision_reason]
        if any(not s.strip() or len(s) > 2000 or any(ord(c) < 32 and c not in '\n\t\r' for c in s) for s in texts):
            raise ValueError('invalid_input')
        if len(canonical(self.model_dump()).encode('utf-8')) > 12000:
            raise ValueError('invalid_input')
        return self


class WriteNoteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: Literal['experience', 'TEST'] = 'experience'
    note_id: str = Field(pattern=r'^(EXP|TEST)-[A-Z0-9][A-Z0-9-]{0,47}$')
    content: NoteContent
    expected_revision: int = Field(ge=0, le=LIMIT_REVISIONS)
    write_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$')


def error(code, *, write=False):
    result = {'status': code, 'reason': ERRORS[code], 'read_only': not write, 'schema_version': 'notes-1'}
    if write:
        result['write_state'] = 'NOT_COMMITTED'
    return result


def render(row):
    content = row['content']
    lines = ['<!-- balatro-note-v1 ' + canonical(row) + ' -->',
             '# ' + row['note_id'], '',
             f"类型：{row['kind']}；修订：{row['revision']}；UTC：{row['created_utc']}", '', '## 来源', '']
    lines += [f"- {s['run_id']}，步骤 " + ', '.join(map(str, s['steps'])) for s in content['sources']]
    for field, label in [('facts', '观察事实'), ('interpretation', '解释或假设'),
                         ('conditions', '适用条件'), ('counterexamples', '反例或待验证项')]:
        lines += ['', '## ' + label, ''] + ['- ' + text.replace('\n', '\n  ') for text in content[field]]
    lines += ['', '## 置信程度', '', content['confidence'], '', '## 修订或保留理由', '', content['revision_reason'], '']
    return '\n'.join(lines)


STRATEGY_FIELDS = ('interpretation', 'conditions', 'counterexamples', 'confidence')
GUIDE_SECTIONS = {'行动判断': 'interpretation',
                  '适用条件': 'conditions', '反例与边界': 'counterexamples'}
CONFIDENCE_LABELS = {'low': '低', 'medium': '中', 'high': '高'}


def strategy_content(content):
    return {key: content[key] for key in STRATEGY_FIELDS}


def render_current(row):
    """Human-readable strategy only; a short update marker binds the commit."""
    content = row['content']
    lines = ['# ' + row['note_id'], f"<!-- 更新标记：{row['revision']} -->"]
    for label, field in GUIDE_SECTIONS.items():
        lines += ['', '## ' + label, '']
        lines += ['- ' + value.replace('\n', '\n  ') for value in content[field]]
    lines += ['', '## 可信程度', '', CONFIDENCE_LABELS[content['confidence']], '']
    return '\n'.join(lines)


def parse_current(markdown):
    content = {field: [] for field in GUIDE_SECTIONS.values()}
    section = None
    for line in markdown.split('\n')[2:]:
        if line.startswith('## '):
            section = GUIDE_SECTIONS.get(line[3:], 'confidence' if line[3:] == '可信程度' else None)
            if section is None:
                raise ValueError()
        elif section == 'confidence' and line:
            content['confidence'] = {label: value for value, label in CONFIDENCE_LABELS.items()}[line]
        elif section in GUIDE_SECTIONS.values() and line.startswith('- '):
            content[section].append(line[2:])
        elif section in GUIDE_SECTIONS.values() and line.startswith('  ') and content[section]:
            content[section][-1] += '\n' + line[2:]
        elif line:
            raise ValueError()
    return content


class NotesStore:
    def __init__(self, root: Path, *, baseline_root: Path | None = None):
        self.root = root.absolute()
        self.baseline = NotesStore(baseline_root) if baseline_root is not None else None
        if self.baseline is not None and (self.root.is_relative_to(self.baseline.root)
                                         or self.baseline.root.is_relative_to(self.root)):
            raise ValueError('unsafe_path')

    def _identity(self, kind, note_id):
        if kind not in ('experience', 'TEST') or not isinstance(note_id, str) or not ID.fullmatch(note_id):
            raise NoteError('invalid_input')
        if not note_id.startswith('EXP-' if kind == 'experience' else 'TEST-'):
            raise NoteError('invalid_input')
        return safe_path(self.root, kind, note_id)

    def _bytes(self, path):
        safe_path(self.root, *path.relative_to(self.root).parts)
        if not path.is_file():
            raise NoteError('store_corrupt')
        with open_file(path, 'rb') as stream:
            data = stream.read(LIMIT_FILE_BYTES + 1)
        if len(data) > LIMIT_FILE_BYTES:
            raise NoteError('store_corrupt')
        return data

    def _local_head(self, kind, note_id):
        folder = self._identity(kind, note_id)
        if kind == 'experience' and self._current_path(note_id).exists():
            return self._current(note_id)['revision']
        path = safe_path(self.root, kind, note_id, 'HEAD.json')
        if not path.exists():
            if kind == 'experience' and folder.exists():
                # A missing committed current file must not expose the baseline.
                raise NoteError('store_corrupt')
            return 0
        try:
            row = json.loads(self._bytes(path))
            if set(row) != {'schema_version', 'note_id', 'kind', 'revision'} or row['schema_version'] != 'notes-1':
                raise ValueError()
            if row['note_id'] != note_id or row['kind'] != kind or type(row['revision']) is not int or not 1 <= row['revision'] <= LIMIT_REVISIONS:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise NoteError('store_corrupt') from None
        return row['revision']

    def _head(self, kind, note_id):
        current = self._local_head(kind, note_id)
        if current == 0 and kind == 'experience' and self.baseline is not None:
            return self.baseline._head(kind, note_id)
        return current

    def _revision(self, kind, note_id, revision):
        if kind == 'experience' and self._current_path(note_id).exists():
            row = self._current(note_id)
            if revision != row['revision']:
                raise NoteError('not_found')
            return row
        # A committed local topic owns its content. Never fill a missing local
        # revision from a baseline that may have independently changed.
        if (kind == 'experience' and self.baseline is not None
                and self._local_head(kind, note_id) == 0
                and revision <= self.baseline._head(kind, note_id)):
            return self.baseline._revision(kind, note_id, revision)
        path = safe_path(self.root, kind, note_id, f'r{revision:04d}.md')
        try:
            markdown = self._bytes(path).decode('utf-8')
            first = markdown.split('\n', 1)[0]
            if not first.startswith('<!-- balatro-note-v1 ') or not first.endswith(' -->'):
                raise ValueError()
            row = json.loads(first[len('<!-- balatro-note-v1 '):-4])
            if set(row) != {'schema_version', 'note_id', 'kind', 'revision', 'created_utc', 'write_id', 'request_hash', 'content'}:
                raise ValueError()
            if row['schema_version'] != 'notes-1' or row['note_id'] != note_id or row['kind'] != kind or type(row['revision']) is not int or row['revision'] != revision:
                raise ValueError()
            if not isinstance(row['created_utc'], str) or len(row['created_utc']) > 40:
                raise ValueError()
            datetime.fromisoformat(row['created_utc'])
            if not isinstance(row['write_id'], str) or not WRITE_ID.fullmatch(row['write_id']) or not isinstance(row['request_hash'], str) or not re.fullmatch('[0-9a-f]{64}', row['request_hash']):
                raise ValueError()
            content = NoteContent.model_validate(row['content']).model_dump()
            self._sources(kind, content)
            request = {'kind': kind, 'note_id': note_id, 'content': content, 'expected_revision': revision - 1, 'write_id': row['write_id']}
            if self._hash(request) != row['request_hash'] or render(row) != markdown:
                raise ValueError()
        except (ValueError, TypeError, KeyError, ValidationError, NoteError):
            raise NoteError('store_corrupt') from None
        return row

    def _current_path(self, note_id):
        self._identity('experience', note_id)
        return safe_path(self.root, 'experience', note_id, 'current.md')

    def _current_legacy(self, note_id):
        """Validate one committed document and compact write identities."""
        try:
            markdown = self._bytes(self._current_path(note_id)).decode('utf-8')
            first = markdown.split('\n', 1)[0]
            prefix = '<!-- balatro-note-v1 '
            if not first.startswith(prefix) or not first.endswith(' -->'):
                raise ValueError()
            row = json.loads(first[len(prefix):-4])
            if set(row) != {'schema_version', 'note_id', 'kind', 'revision', 'created_utc',
                            'write_id', 'request_hash', 'content', 'write_receipts'}:
                raise ValueError()
            if (row['schema_version'] != 'notes-1' or row['note_id'] != note_id
                    or row['kind'] != 'experience' or type(row['revision']) is not int
                    or not 1 <= row['revision'] <= LIMIT_REVISIONS):
                raise ValueError()
            content = NoteContent.model_validate(row['content']).model_dump()
            self._sources('experience', content)
            receipts = row['write_receipts']
            if not isinstance(receipts, dict) or len(receipts) != row['revision']:
                raise ValueError()
            revisions = []
            for write_id, receipt in receipts.items():
                if (not isinstance(write_id, str) or not WRITE_ID.fullmatch(write_id)
                        or not isinstance(receipt, dict)
                        or set(receipt) != {'revision', 'created_utc', 'request_hash'}
                        or type(receipt['revision']) is not int
                        or not 1 <= receipt['revision'] <= row['revision']
                        or not isinstance(receipt['created_utc'], str)
                        or len(receipt['created_utc']) > 40
                        or not isinstance(receipt['request_hash'], str)
                        or not re.fullmatch('[0-9a-f]{64}', receipt['request_hash'])):
                    raise ValueError()
                datetime.fromisoformat(receipt['created_utc'])
                revisions.append(receipt['revision'])
            if sorted(revisions) != list(range(1, row['revision'] + 1)):
                raise ValueError()
            receipt = receipts[row['write_id']]
            if receipt != {key: row[key] for key in ('revision', 'created_utc', 'request_hash')}:
                raise ValueError()
            request = {'kind': 'experience', 'note_id': note_id, 'content': content,
                       'expected_revision': row['revision'] - 1, 'write_id': row['write_id']}
            if self._hash(request) != row['request_hash'] or render(row) != markdown:
                raise ValueError()
        except (ValueError, TypeError, KeyError, ValidationError, NoteError):
            raise NoteError('store_corrupt') from None
        return row

    def _metadata_path(self, note_id):
        self._identity('experience', note_id)
        return safe_path(self.root, '.metadata', 'experience', note_id + '.json')

    def _current(self, note_id):
        """The Markdown hash chooses committed metadata, never a pending intent."""
        data = self._bytes(self._current_path(note_id))
        if data.startswith(b'<!-- balatro-note-v1 '):
            return self._current_legacy(note_id)
        try:
            markdown = data.decode('utf-8')
            digest = hashlib.sha256(data).hexdigest()
            candidates = None
            for _ in range(2):
                metadata = json.loads(self._bytes(self._metadata_path(note_id)))
                if (set(metadata) != {'schema', 'candidates'} or metadata['schema'] != 'strategy-audit-v1'
                        or not isinstance(metadata['candidates'], list)
                        or not 1 <= len(metadata['candidates']) <= 2
                        or any(not isinstance(row,dict) for row in metadata['candidates'])):
                    raise ValueError()
                candidates = [row for row in metadata['candidates'] if row.get('markdown_sha256') == digest]
                if len(candidates) == 1:
                    break
            if len(candidates) != 1:
                raise ValueError()
            metadata = candidates[0]
            if set(metadata) != {'schema_version', 'note_id', 'kind', 'revision', 'created_utc',
                                 'write_id', 'request_hash', 'write_receipts', 'sources',
                                 'revision_reason', 'facts', 'markdown_sha256'}:
                raise ValueError()
            content = parse_current(markdown) | {key: metadata[key] for key in ('sources', 'revision_reason','facts')}
            row = {key: value for key, value in metadata.items()
                   if key not in ('sources', 'revision_reason', 'facts', 'markdown_sha256')} | {'content': content}
            # Reuse the legacy structural/hash validator on the reconstructed row.
            self._validate_current_row(note_id, row)
            if render_current(row) != markdown:
                raise ValueError()
            return row
        except (ValueError, TypeError, KeyError, ValidationError, NoteError):
            raise NoteError('store_corrupt') from None

    def _validate_current_row(self, note_id, row):
        if (set(row) != {'schema_version','note_id','kind','revision','created_utc','write_id',
                        'request_hash','write_receipts','content'}
                or row['schema_version'] != 'notes-1' or row['note_id'] != note_id
                or row['kind'] != 'experience' or type(row['revision']) is not int
                or not 1 <= row['revision'] <= LIMIT_REVISIONS):
            raise ValueError()
        content = NoteContent.model_validate(row['content']).model_dump()
        self._sources('experience', content)
        receipts = row['write_receipts']
        if not isinstance(receipts, dict) or len(receipts) != row['revision']:
            raise ValueError()
        revisions = []
        for write_id, receipt in receipts.items():
            if (not isinstance(write_id,str) or not WRITE_ID.fullmatch(write_id)
                    or not isinstance(receipt,dict) or set(receipt) != {'revision','created_utc','request_hash'}
                    or type(receipt['revision']) is not int or not 1 <= receipt['revision'] <= row['revision']
                    or not isinstance(receipt['created_utc'],str) or len(receipt['created_utc']) > 40
                    or not isinstance(receipt['request_hash'],str) or not re.fullmatch('[0-9a-f]{64}',receipt['request_hash'])):
                raise ValueError()
            datetime.fromisoformat(receipt['created_utc'])
            revisions.append(receipt['revision'])
        if sorted(revisions) != list(range(1,row['revision']+1)):
            raise ValueError()
        if receipts[row['write_id']] != {key:row[key] for key in ('revision','created_utc','request_hash')}:
            raise ValueError()
        request = {'kind':'experience','note_id':note_id,'content':content,
                   'expected_revision':row['revision']-1,'write_id':row['write_id']}
        if self._hash(request) != row['request_hash']:
            raise ValueError()

    def install_current(self, row):
        """Stage audit metadata first; atomic Markdown replacement commits the note."""
        self._validate_current_row(row['note_id'], row)
        note_id = row['note_id']
        path = self._current_path(note_id)
        data = render_current(row).encode('utf-8')
        metadata_path = self._metadata_path(note_id)
        make_dir(metadata_path.parent)
        make_dir(path.parent)
        def metadata_for(document, markdown):
            return {key:value for key,value in document.items() if key != 'content'} | {
                'sources':document['content']['sources'],
                'facts':document['content']['facts'],
                'revision_reason':document['content']['revision_reason'],
                'markdown_sha256':hashlib.sha256(markdown).hexdigest()}
        current_metadata = metadata_for(row,data)
        candidates = [current_metadata]
        if path.exists():
            old = self._current(note_id)
            old_data = self._bytes(path)
            if old_data != data:
                candidates.insert(0,metadata_for(old,old_data))
        prepared = canonical({'schema':'strategy-audit-v1','candidates':candidates}).encode('utf-8')
        if max(len(data),len(prepared)) > LIMIT_FILE_BYTES:
            raise NoteError('resource_limit')
        self._atomic(metadata_path,prepared)
        self._atomic(path,data)
        # Pruning redundant metadata is optional after the Markdown commit. A
        # failed prune never keeps old strategy bodies or rewinds the current note.
        if len(candidates) > 1:
            try:
                self._atomic(metadata_path,canonical({'schema':'strategy-audit-v1','candidates':[current_metadata]}).encode('utf-8'))
            except OSError:
                pass

    def current_document(self, note_id):
        """Build the current document from validated legacy data, without writing."""
        if self._current_path(note_id).exists():
            return self._current(note_id)
        current = self._local_head('experience', note_id)
        if current == 0:
            raise NoteError('not_found')
        receipts = {}
        for revision in range(1, current + 1):
            row = self._revision('experience', note_id, revision)
            if row['write_id'] in receipts:
                raise NoteError('store_corrupt')
            receipts[row['write_id']] = {key: row[key] for key in
                                        ('revision', 'created_utc', 'request_hash')}
        return {**row, 'write_receipts': receipts}

    def _write_current(self, request):
        note_id = request['note_id']
        local_revision = self._local_head('experience', note_id)
        if local_revision and not self._current_path(note_id).exists():
            raise NoteError('migration_required')
        source = self if local_revision else self.baseline
        current = source._head('experience', note_id) if source is not None else 0
        existing = source.current_document(note_id) if current else None
        receipts = dict(existing['write_receipts']) if existing else {}
        digest = self._hash(request)
        receipt = receipts.get(request['write_id'])
        if receipt is not None:
            if receipt['request_hash'] != digest:
                raise NoteError('id_conflict')
            # The caller supplies the exact old content; only its validated hash
            # was retained. A duplicate never rewinds the current document.
            row = {'schema_version': 'notes-1', 'note_id': note_id, 'kind': 'experience',
                   **receipt, 'write_id': request['write_id'], 'content': request['content']}
            return {'status': 'ok', 'schema_version': 'notes-1', 'read_only': False,
                    'write_state': 'COMMITTED', 'duplicate': True,
                    'historical_receipt': receipt['revision'] != current,
                    'note': self._public(row, current)}
        if current != request['expected_revision']:
            raise NoteError('revision_conflict')
        if current >= LIMIT_REVISIONS:
            raise NoteError('resource_limit')
        row = {'schema_version': 'notes-1', 'note_id': note_id, 'kind': 'experience',
               'revision': current + 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
               'write_id': request['write_id'], 'request_hash': digest, 'content': request['content']}
        receipts[row['write_id']] = {key: row[key] for key in ('revision', 'created_utc', 'request_hash')}
        row['write_receipts'] = receipts
        data = render_current(row).encode('utf-8')
        if len(data) > LIMIT_FILE_BYTES:
            raise NoteError('resource_limit')
        folder = self._identity('experience', note_id)
        make_dir(folder)
        try:
            if not local_revision and source is not None and source._head('experience', note_id) != current:
                raise NoteError('revision_conflict')
            self.install_current(row)
        finally:
            # Ordinary first-write failures leave no ownership marker. A crash
            # residue remains fail-closed and requires explicit maintenance.
            if not self._current_path(note_id).exists():
                try:
                    safe_path(self.root, 'experience', note_id).rmdir()
                except OSError:
                    pass
        return {'status': 'ok', 'schema_version': 'notes-1', 'read_only': False,
                'write_state': 'COMMITTED', 'duplicate': False, 'note': self._public(row, current + 1)}

    @staticmethod
    def _sources(kind, content):
        prefix = 'n5-' if kind == 'experience' else 'test-'
        if any(not source['run_id'].startswith(prefix) for source in content['sources']):
            raise NoteError('invalid_input')

    @staticmethod
    def _hash(request):
        return hashlib.sha256(canonical(request).encode('utf-8')).hexdigest()

    def _ids(self, kind):
        folder = safe_path(self.root, kind)
        ids = []
        # Bounded scan, including incomplete creates; unknown children fail closed.
        for item in folder.iterdir() if folder.exists() else ():
            self._identity(kind, item.name)
            if not item.is_dir():
                raise NoteError('store_corrupt')
            ids.append(item.name)
            if len(ids) > LIMIT_NOTES:
                raise NoteError('resource_limit')
        if kind == 'experience' and self.baseline is not None:
            ids = set(ids).union(self.baseline._ids(kind))
            if len(ids) > LIMIT_NOTES:
                raise NoteError('resource_limit')
        return sorted(ids)

    @staticmethod
    def _public(row, current):
        return {key: row[key] for key in ('note_id', 'kind', 'revision', 'created_utc', 'write_id', 'content')} | {
            'current_revision': current, 'markdown': render_current(row) if row['kind']=='experience' else render(row), 'source_validation': 'model_supplied_audit_required'}

    @staticmethod
    def _strategy(note):
        if note['kind'] != 'experience':
            return {key:value for key,value in note.items() if key != 'markdown'}
        return {key:note[key] for key in ('note_id','kind','revision','current_revision')} | {
            'content':strategy_content(note['content'])}

    def read(self, kind='experience', note_ids=None, revision=None, view='full', query=None, offset=0):
        if kind not in ('experience', 'TEST') or view not in ('full', 'content', 'index', 'strategy'):
            raise NoteError('invalid_input')
        if (type(offset) is not int or not 0 <= offset <= LIMIT_NOTES
                or (view != 'index' and (query is not None or offset != 0))
                or (query is not None and (not isinstance(query, str) or len(query) > 80
                    or any(ord(c) < 32 for c in query)))):
            raise NoteError('invalid_input')
        if note_ids is not None and (not isinstance(note_ids, list) or len(note_ids) > 20 or any(not isinstance(n, str) for n in note_ids) or len(set(note_ids)) != len(note_ids)):
            raise NoteError('invalid_input')
        if revision is not None and (type(revision) is not int or not 1 <= revision <= LIMIT_REVISIONS or note_ids is None or len(note_ids) != 1):
            raise NoteError('invalid_input')
        ids = self._ids(kind) if note_ids is None else note_ids
        if len(ids) > 20 and view != 'index':
            raise NoteError('resource_limit')
        notes = []
        for note_id in ids:
            current = self._head(kind, note_id)
            if current == 0:
                if note_ids is None:
                    continue
                raise NoteError('not_found')
            selected = revision if revision is not None else current
            if selected > current:
                raise NoteError('not_found')
            row = self._revision(kind, note_id, selected)
            if view == 'index':
                # Literal retrieval only: no model, relevance score or strategy.
                content = row['content']
                text = canonical({'note_id': note_id, 'content': strategy_content(content) if kind=='experience' else content}).casefold()
                if query and query.strip().casefold() not in text:
                    continue
                previews = content['conditions'][:2]
                notes.append({'note_id': note_id, 'revision': selected, 'current_revision': current,
                              'note_ref': f'{note_id}@r{selected}', 'confidence': content['confidence'],
                              'rule_preview' if kind=='experience' else 'fact_preview': content['interpretation' if kind=='experience' else 'facts'][0][:120],
                              'condition_previews': [s[:120] for s in previews],
                              'counterexample_preview': content['counterexamples'][0][:120],
                              'preview_only': True})
            else:
                notes.append(self._public(row, current))
        if view == 'content':
            for note in notes:
                del note['markdown']
        if view == 'strategy':
            notes = [self._strategy(note) for note in notes]
        result = {'status': 'ok', 'schema_version': 'notes-1', 'read_only': True, 'kind': kind, 'notes': notes}
        if view == 'index':
            total = len(notes)
            result.update(notes=notes[offset:offset + 20], total_matches=total, discovery_only=True,
                          next_offset=offset + 20 if offset + 20 < total else None)
        if len(canonical(result).encode('utf-8')) > LIMIT_RESPONSE_BYTES:
            raise NoteError('resource_limit')
        return result

    def request(self, kind, note_id, content, expected_revision, write_id):
        self._identity(kind, note_id)
        try:
            request = WriteNoteRequest.model_validate({'kind': kind, 'note_id': note_id, 'content': content,
                                                       'expected_revision': expected_revision, 'write_id': write_id}).model_dump()
        except (ValueError, TypeError, ValidationError):
            raise NoteError('invalid_input') from None
        self._sources(kind, request['content'])
        return request

    def _atomic(self, path, data):
        temporary = safe_path(self.root, *path.parent.relative_to(self.root).parts, '.tmp-' + uuid.uuid4().hex)
        try:
            with open_file(temporary, 'xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            safe_path(self.root, *path.relative_to(self.root).parts)
            replace_file(temporary, path)
        finally:
            if temporary.exists():
                safe_path(self.root, *temporary.relative_to(self.root).parts)
                temporary.unlink()

    def write(self, request):
        kind, note_id = request['kind'], request['note_id']
        make_dir(self.root)
        lock = safe_path(self.root, '.writer-lock')
        try:
            lock.mkdir()
        except FileExistsError:
            raise NoteError('busy') from None
        try:
            ids = self._ids(kind)
            if note_id not in ids and len(ids) >= LIMIT_NOTES:
                raise NoteError('resource_limit')
            if kind == 'experience':
                return self._write_current(request)
            current = self._head(kind, note_id)
            digest = self._hash(request)
            for revision in range(1, current + 1):
                row = self._revision(kind, note_id, revision)
                if row['write_id'] == request['write_id']:
                    if row['request_hash'] != digest:
                        raise NoteError('id_conflict')
                    return {'status': 'ok', 'schema_version': 'notes-1', 'read_only': False,
                            'write_state': 'COMMITTED', 'duplicate': True, 'note': self._public(row, current)}
            if current != request['expected_revision']:
                raise NoteError('revision_conflict')
            if current >= LIMIT_REVISIONS:
                raise NoteError('resource_limit')
            folder = self._identity(kind, note_id)
            make_dir(folder)
            revision = current + 1
            path = safe_path(self.root, kind, note_id, f'r{revision:04d}.md')
            if path.exists():
                # A failed HEAD commit left an immutable orphan. Reuse only same request.
                row = self._revision(kind, note_id, revision)
                if row['request_hash'] != digest:
                    raise NoteError('storage_unavailable')
            else:
                row = {'schema_version': 'notes-1', 'note_id': note_id, 'kind': kind, 'revision': revision,
                       'created_utc': datetime.now(timezone.utc).isoformat(), 'write_id': request['write_id'],
                       'request_hash': digest, 'content': request['content']}
                self._atomic(path, render(row).encode('utf-8'))
            head = {key: row[key] for key in ('schema_version', 'note_id', 'kind', 'revision')}
            self._atomic(safe_path(self.root, kind, note_id, 'HEAD.json'), canonical(head).encode('utf-8'))
            return {'status': 'ok', 'schema_version': 'notes-1', 'read_only': False,
                    'write_state': 'COMMITTED', 'duplicate': False, 'note': self._public(row, revision)}
        finally:
            safe_path(self.root, '.writer-lock')
            # A cleanup error must never misreport a committed HEAD as uncommitted.
            # A remaining lock blocks future writes and is preserved for review.
            try:
                lock.rmdir()
            except OSError:
                pass


class NotesService:
    def __init__(self, settings, *, activity=None):
        self.store = NotesStore(settings.notes_dir, baseline_root=settings.baseline_notes_dir)
        self.audit = LocalAudit(settings, activity=activity)
        self.read_refs = set()

    @staticmethod
    def _failure(exc, write=False):
        code = str(exc) if isinstance(exc, NoteError) else 'unsafe_path' if isinstance(exc, ValueError) and str(exc) == 'unsafe_path' else 'storage_unavailable'
        return error(code if code in ERRORS else 'storage_unavailable', write=write)

    def read_notes(self, kind='experience', note_ids=None, revision=None, view='full', query=None, offset=0):
        try:
            result = self.store.read(kind, note_ids, revision, view, query, offset)
        except (NoteError, OSError, ValueError, TypeError) as exc:
            result = self._failure(exc)
        delivered = self.audit.deliver('read_notes', result)
        if delivered.get('status') == 'ok' and kind == 'experience' and view != 'index':
            self.read_refs.update(f"{note['note_id']}@r{note['revision']}" for note in delivered['notes'])
        return delivered

    def write_note(self, note_id, content, expected_revision, write_id, kind='experience', view='full'):
        try:
            if view not in ('content', 'full', 'strategy'):
                raise NoteError('invalid_input')
            request = self.store.request(kind, note_id, content, expected_revision, write_id)
            try:
                self.audit.record('write_note', 'intent', request)
            except (OSError, ValueError):
                raise NoteError('log_unavailable') from None
            result = self.store.write(request)
            if view == 'content':
                result['note'] = {key: value for key, value in result['note'].items() if key != 'markdown'}
            if view == 'strategy':
                result['note'] = self.store._strategy(result['note'])
        except (NoteError, OSError, ValueError, TypeError) as exc:
            result = self._failure(exc, write=True)
        return self.audit.deliver('write_note', result, write=True)
