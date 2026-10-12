"""Rebuild a source candidate in a fresh directory using verified cached sources."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
import uuid
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from bootstrap_sources import no_links, digest, unpack

ROOT=Path(__file__).resolve().parents[1]


def run_checks(commands, target, environment):
    """Bound verification stages and keep real failure evidence without retrying."""
    results=[]
    for kind,command in commands:
        # Full public suites launch many isolated Windows processes. Their
        # verification budget is separate from gameplay transport deadlines.
        budget=300 if kind=='public_synthetic' else 120
        try:
            result=subprocess.run(command,cwd=target,env=environment,capture_output=True,text=True,
                encoding='utf-8',errors='replace',timeout=budget)
        except subprocess.TimeoutExpired as exc:
            def decoded(value):
                return value.decode('utf-8',errors='replace') if isinstance(value,bytes) else value or ''
            results.append({'kind':kind,'exit_code':None,'timed_out':True,'timeout_s':budget,
                'output':(decoded(exc.stdout)+decoded(exc.stderr))[-3500:]})
            break
        results.append({'kind':kind,'exit_code':result.returncode,
            'output':(result.stdout+result.stderr)[-3500:]})
        if result.returncode:break
    return results


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='runs/checks/source-candidate-validation.json')
    args=parser.parse_args()
    output=(ROOT/args.output).absolute()
    if '..' in output.parts or not output.is_relative_to(ROOT/'runs/checks'):
        raise ValueError('Validation output belongs under runs/checks')
    no_links(output)
    if output.exists():raise ValueError('Preserve existing validation and use a new output')
    version=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    companion=ROOT/'deliverables/source'/('balatro-agent-'+version+'-source-validation.json')
    no_links(companion)
    if companion.exists():raise ValueError('Preserve existing source validation companion and its candidate')
    archive=ROOT/'deliverables/source'/('balatro-agent-'+version+'-source-candidate.zip')
    no_links(archive)
    # Keep nested Windows test/backup paths below the legacy path limit.
    # A collision is still refused by unpack; previous receipts are preserved.
    target=ROOT/'.artifacts'/('sv-'+uuid.uuid4().hex[:16])
    no_links(target)
    with ZipFile(archive) as bundle:
        manifest=json.loads(bundle.read('SOURCE-MANIFEST.json'))
        if manifest['version']!=version or manifest['current_version_real_game_verified'] is not False:
            raise ValueError('Candidate scope differs from its checked-source contract')
        names=[i['path'] for i in manifest['files']]
        if len(set(names))!=len(names) or set(bundle.namelist())!=set(names)|{'SOURCE-MANIFEST.json'}:
            raise ValueError('Source manifest member list differs')
        import hashlib
        for entry in manifest['files']:
            if hashlib.sha256(bundle.read(entry['path'])).hexdigest()!=entry['sha256']:
                raise ValueError('Source manifest hash mismatch')
    unpack(archive,target)
    environment=dict(os.environ)
    environment['PYTHONPATH']=str(target/'src')
    environment['BALATRO_AGENT_CLIENT_CONTEXT']='development'
    environment['PYTHONDONTWRITEBYTECODE']='1'
    environment['PYTHONUTF8']='1'
    commands=[
        ('bootstrap',[sys.executable,str(target/'scripts/bootstrap_sources.py'),'--cache',str(ROOT/'.artifacts/sources'),'--offline']),
        ('build',[sys.executable,str(target/'scripts/build_mod.py')]),
        ('public_synthetic',[sys.executable,'-m','pytest','-q','--tb=short','-p','no:cacheprovider',
            '--basetemp='+str(target/'pytest-tmp'),'--junitxml='+str(target/'public-tests.xml')]),
        ('development_stdio',[sys.executable,str(target/'scripts/stdio_smoke.py'),'--output','runs/checks/public-stdio.json']),
    ]
    results=run_checks(commands,target,environment)
    original=json.loads((ROOT/'mod/build-manifest.json').read_text(encoding='utf-8'))
    rebuilt=target/'mod/build-manifest.json'
    match=rebuilt.is_file() and json.loads(rebuilt.read_text(encoding='utf-8'))==original
    totals={key:0 for key in ('tests','failures','errors','skipped')}
    if (target/'public-tests.xml').exists():
        for suite in ET.parse(target/'public-tests.xml').getroot().iter('testsuite'):
            for key in totals:totals[key]+=int(suite.get(key,0))
    scope={'evidence_type':'independent_source_candidate_rebuild','version':version,
        'utc':datetime.now(timezone.utc).isoformat(),'archive_sha256':digest(archive),
        'source_manifest_hashes_match':True,'fresh_mod_build_matches_source_manifest':match,
        'pinned_dependencies_offline_verified':bool(results) and results[0]['exit_code']==0,
        'public_synthetic':totals,'development_stdio_verified':len(results)==4 and results[-1]['exit_code']==0,
        'private_native_functions_included':False,'current_version_real_game_verified':False,
        'game_or_client_config_changed':False,'published':False,'file_count':len(manifest['files'])+1}
    report={**scope,'validation_directory':target.relative_to(ROOT).as_posix(),'commands':results}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    success=(len(results)==4 and all(i['exit_code']==0 for i in results) and match
             and totals['tests']>0 and totals['failures']==totals['errors']==0)
    if success:
        with companion.open('x',encoding='utf-8') as stream:stream.write(json.dumps(scope,indent=2)+'\n')
    print(json.dumps(scope))
    if not success:raise ValueError('Independent source candidate rebuild did not pass; keep its report')


if __name__=='__main__':main()
