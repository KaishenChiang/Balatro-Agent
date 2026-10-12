"""Explicit maintenance promotion of current local topics, without publication."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid
import zipfile

from balatro_agent.local_audit import canonical, make_dir, safe_path
from balatro_agent.notes import NotesStore


def digest(data):
    return hashlib.sha256(data).hexdigest()


def promote(root, *, apply=False, output=None):
    root = Path(root).absolute()
    baseline = NotesStore(root/'experience')
    local = NotesStore(root/'runs/local-experience')
    locks = []
    try:
        if apply:
            for store in (baseline, local):
                make_dir(store.root)
                lock = safe_path(store.root, '.writer-lock')
                lock.mkdir()
                locks.append(lock)
        pairs = []
        for note_id in local._ids('experience'):
            current = local._current(note_id)
            source_path = baseline._current_path(note_id)
            target_path = local._current_path(note_id)
            for store in (baseline, local):
                folder = store._identity('experience', note_id)
                if folder.exists() and list(folder.iterdir()) != [store._current_path(note_id)]:
                    raise ValueError('Migrate legacy topics before promotion')
            source = baseline._current(note_id) if source_path.exists() else None
            old = source_path.read_bytes() if source else None
            new = target_path.read_bytes()
            if source == current:
                continue
            # Never silently discard an independently updated source branch.
            if source and any(current['write_receipts'].get(write_id) != receipt
                              for write_id, receipt in source['write_receipts'].items()):
                raise ValueError('Source and local topic conflict; review both contents')
            pairs.append((note_id, source_path, target_path, old, new, current))
        report = {'evidence_type':'explicit_local_experience_promotion', 'apply':apply,
                  'topics':[{'note_id':note_id,'update_counter':row['revision'],
                             'content_sha256':digest(canonical(row['content']).encode('utf-8'))}
                            for note_id, _, _, _, _, row in pairs],
                  'storage_format':'single-current-v2', 'changes_game_state':False,
                  'published':False, 'local_files_changed':False}
        if not apply or not pairs:
            return report | {'state':'PLANNED' if not apply else 'ALREADY_INTEGRATED'}
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
        archive = safe_path(root, '.artifacts','experience-promotion',stamp,'before-promotion.zip')
        make_dir(archive.parent)
        frozen = {}
        for _, source_path, target_path, old, new, _ in pairs:
            if old is not None:
                frozen[source_path.relative_to(root).as_posix()] = old
            frozen[target_path.relative_to(root).as_posix()] = new
        for note_id, _, _, _, _, _ in pairs:
            for store in (baseline,local):
                path=store._metadata_path(note_id)
                if path.exists():
                    frozen[path.relative_to(root).as_posix()]=path.read_bytes()
        with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as bundle:
            for name,data in frozen.items():
                bundle.writestr(name,data)
            bundle.writestr('ARCHIVE-MANIFEST.json',canonical({name:digest(data) for name,data in frozen.items()}))
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None or any(bundle.read(name)!=data for name,data in frozen.items()):
                raise ValueError('Promotion archive verification failed')
        report.update(archive=archive.relative_to(root).as_posix(),
                      archive_sha256=digest(archive.read_bytes()),state='ARCHIVED')
        report_path = safe_path(root,*(Path(output).parts if output else
                                     ('runs','checks','experience-promotion-'+stamp+'.json')))
        if not report_path.is_relative_to(root/'runs/checks') or report_path.exists():
            raise ValueError('Choose a new promotion report under runs/checks')
        make_dir(report_path.parent)
        def save_report():
            NotesStore(root)._atomic(report_path,(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
        save_report()
        try:
            for note_id, source_path, target_path, old, new, current in pairs:
                for store in (baseline,local):
                    path=store._metadata_path(note_id)
                    name=path.relative_to(root).as_posix()
                    if name in frozen and path.read_bytes()!=frozen[name]:
                        raise ValueError('Audit metadata changed after archive')
                if (target_path.read_bytes()!=new
                        or (source_path.read_bytes() if source_path.exists() else None)!=old):
                    raise ValueError('Experience changed after archive')
                make_dir(source_path.parent)
                baseline.install_current(current)
                if baseline._current(note_id)!=current or source_path.read_bytes()!=new:
                    raise ValueError('Promoted topic readback mismatch')
            if any(target.read_bytes()!=new for _, _, target, _, new, _ in pairs):
                raise ValueError('Local experience changed during promotion')
            report.update(state='COMPLETED', topics_verified=len(pairs),
                          source_matches_local=True, report=report_path.relative_to(root).as_posix())
        except Exception:
            report['state']='PARTIAL_FAILURE'
            save_report()
            raise
        save_report()
        return report
    finally:
        for lock in reversed(locks):
            lock.rmdir()
