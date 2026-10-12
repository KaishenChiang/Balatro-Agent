"""Archive legacy experience once, then retain one current file per topic."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
import zipfile

from balatro_agent.local_audit import canonical, make_dir, safe_path
from balatro_agent.notes import NotesStore, render_current


def digest(data):
    return hashlib.sha256(data).hexdigest()


def migrate(root, *, apply=False, output=None):
    root = Path(root).absolute()
    stores = [NotesStore(root / 'experience'), NotesStore(root / 'runs/local-experience')]
    locks = []
    try:
        if apply:
            for store in stores:
                make_dir(store.root)
                lock = safe_path(store.root, '.writer-lock')
                lock.mkdir()  # Never remove another writer's lock.
                locks.append(lock)
        topics = []
        frozen = {}
        before = {}
        for store in stores:
            for note_id in store._ids('experience'):
                document = store.current_document(note_id)
                folder = store._identity('experience', note_id)
                current = store._current_path(note_id)
                before[(str(store.root), note_id)] = document['content']
                metadata_path = store._metadata_path(note_id)
                if metadata_path.exists():
                    frozen[metadata_path.relative_to(root).as_posix()] = metadata_path.read_bytes()
                files = []
                for path in sorted(folder.rglob('*')):
                    safe_path(root, *path.relative_to(root).parts)
                    if path.is_file():
                        data = path.read_bytes()
                        relative = path.relative_to(root).as_posix()
                        frozen[relative] = data
                        if path != current:
                            files.append(path)
                topics.append((store, note_id, document, files))
        conversions = sum(not store._current_path(note_id).exists() or store._current_path(note_id).read_bytes() != render_current(document).encode('utf-8')
                          for store,note_id,document,_ in topics)
        legacy = sum(len(files) for _, _, _, files in topics)
        report = {'evidence_type': 'local_experience_storage_migration',
                  'storage_format': 'single-current-v2', 'apply': apply,
                  'topics': len(topics), 'legacy_files_to_archive': legacy,
                  'legacy_documents_to_convert': conversions,
                  'changes_game_state': False, 'codex_client_reloaded': False}
        if not apply or legacy == conversions == 0:
            return report | {'state': 'PLANNED' if not apply else 'ALREADY_CURRENT'}
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        backup_dir = safe_path(root, '.artifacts', 'experience-archive', stamp)
        make_dir(backup_dir)
        archive = backup_dir / 'legacy-experience.zip'
        manifest = {name: {'sha256': digest(data), 'bytes': len(data)}
                    for name, data in frozen.items()}
        with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
            for name, data in frozen.items():
                bundle.writestr(name, data)
            bundle.writestr('ARCHIVE-MANIFEST.json', canonical(manifest))
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None:
                raise ValueError('Archive verification failed')
            for name, metadata in manifest.items():
                data = bundle.read(name)
                if len(data) != metadata['bytes'] or digest(data) != metadata['sha256']:
                    raise ValueError('Archive member mismatch')
        report['archive'] = archive.relative_to(root).as_posix()
        report['archive_sha256'] = digest(archive.read_bytes())
        report['archive_members_verified'] = len(manifest)
        report['state'] = 'ARCHIVED'
        report_path = safe_path(root, *(Path(output).parts if output else
                                     ('runs', 'checks', 'experience-single-' + stamp + '.json')))
        if not report_path.is_relative_to(root / 'runs/checks') or report_path.exists():
            raise ValueError('Choose a new migration report under runs/checks')
        make_dir(report_path.parent)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        try:
            for store, note_id, document, files in topics:
                for path in files:
                    relative = path.relative_to(root).as_posix()
                    if path.read_bytes() != frozen[relative]:
                        raise ValueError('Source changed after archive')
                store.install_current(document)
                if store._current(note_id) != document:
                    raise ValueError('Current document verification failed')
                for path in files:
                    # Only exact archived members inside these experience topics.
                    checked = safe_path(root, *path.relative_to(root).parts)
                    if not checked.is_relative_to(store.root / 'experience'):
                        raise ValueError('Unsafe cleanup target')
                    if checked.read_bytes() != frozen[checked.relative_to(root).as_posix()]:
                        raise ValueError('Cleanup member changed')
                    checked.unlink()
                folder = store._identity('experience', note_id)
                for path in sorted((p for p in folder.rglob('*') if p.is_dir()),
                                   key=lambda p: len(p.parts), reverse=True):
                    safe_path(root, *path.relative_to(root).parts).rmdir()
                if list(folder.iterdir()) != [store._current_path(note_id)]:
                    raise ValueError('Unexpected current topic files')
                if store.read(note_ids=[note_id], view='content')['notes'][0]['content'] != before[(str(store.root), note_id)]:
                    raise ValueError('Experience content changed')
            report.update(state='COMPLETED', current_topics_verified=len(topics),
                          content_unchanged=True, report=report_path.relative_to(root).as_posix())
        except Exception:
            report['state'] = 'PARTIAL_FAILURE'
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            raise
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return report
    finally:
        for lock in reversed(locks):
            lock.rmdir()
