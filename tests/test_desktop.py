"""Real WinExe/PowerShell boundaries with synthetic workers and local HTTP only."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

import pytest

from test_setup import ROOT, PS, quote, run_helpers

sys.path.insert(0,str(ROOT/'scripts'))
from package_source import verify_launcher


@pytest.mark.parametrize('mode',['resume','ignore_range','invalid_range'])
def test_download_resumes_only_matching_range_and_preserves_original(tmp_path,mode):
    body=b'public synthetic archive'*5000
    original=tmp_path/('download.zip.'+'1'*32+'.part')
    prefix=body[:23000];original.write_bytes(prefix)
    ranges=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            ranges.append(self.headers.get('Range'))
            if mode=='ignore_range':
                content=body;self.send_response(200)
            else:
                content=body[len(prefix):];self.send_response(206)
                start=len(prefix) if mode=='resume' else len(prefix)+1
                self.send_header('Content-Range',f'bytes {start}-{len(body)-1}/{len(body)}')
            self.send_header('Content-Length',str(len(content)));self.end_headers()
            self.wfile.write(content)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    item={'url':f'http://127.0.0.1:{server.server_port}/archive','sha256':hashlib.sha256(body).hexdigest()}
    try:
        result=run_helpers(tmp_path,item,"Receive-LockedArchive $item (Join-Path $root 'download.zip') 2 0")
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
    assert original.read_bytes()==prefix and ranges==[f'bytes={len(prefix)}-']
    if mode=='invalid_range':
        assert result.returncode!=0 and not (tmp_path/'download.zip').exists()
    else:
        assert result.returncode==0,result.stderr
        assert (tmp_path/'download.zip').read_bytes()==body


def test_stalled_download_times_out_and_retries_with_bounded_wait(tmp_path):
    if not PS:pytest.skip('Windows PowerShell')
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path);self.send_response(200)
            self.send_header('Content-Length','10000');self.end_headers()
            time.sleep(3)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    started=time.monotonic()
    try:
        result=run_helpers(tmp_path,{'url':f'http://127.0.0.1:{server.server_port}/stall','sha256':'0'*64},
            "Receive-LockedArchive $item (Join-Path $root 'download.zip') 1 1")
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
    assert result.returncode!=0 and not (tmp_path/'download.zip').exists()
    assert len(calls)==2 and time.monotonic()-started<10


def test_progress_receipt_is_updated_atomically_and_bound_to_launch(tmp_path):
    path=tmp_path/'progress.json'
    operation="$env:BALATRO_SETUP_PROGRESS="+quote(path)+";$env:BALATRO_SETUP_ID='new-launch';$env:BALATRO_SETUP_STAGE='1';"
    operation+="Write-PreparationProgress 'connecting' 'uv';Write-PreparationProgress 'downloading' 'uv' 1024 2048 512;"
    operation+="Write-PreparationProgress 'verifying' 'uv' 2048 2048 0"
    result=run_helpers(tmp_path,{},operation)
    assert result.returncode==0,result.stderr
    value=json.loads(path.read_text())
    assert value['preparation_id']=='new-launch' and value['state']=='verifying'
    assert value['received_bytes']==value['total_bytes']==2048
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('exit_code',[0,19])
def test_real_exe_uses_unicode_project_and_creates_no_console(tmp_path,exit_code):
    if not PS:pytest.skip('Windows WinExe')
    root=tmp_path/'中文 path & bang!';scripts=root/'scripts';scripts.mkdir(parents=True)
    executable=root/'Balatro Agent.exe';shutil.copyfile(ROOT/executable.name,executable)
    source="param([switch]$Preview,[string]$PreviewImage,[string]$PreviewState)\n"
    source+="Add-Type 'using System; using System.Runtime.InteropServices; public static class ConsoleProbe { [DllImport(\"kernel32.dll\")] public static extern IntPtr GetConsoleWindow(); }'\n"
    source+="$value=@{root=$PSScriptRoot;console=[ConsoleProbe]::GetConsoleWindow().ToInt64();image=$PreviewImage;preview=[bool]$Preview}\n"
    source+="[IO.File]::WriteAllText((Join-Path $PSScriptRoot '../called.json'),($value|ConvertTo-Json))\n"
    source+=f'exit {exit_code}\n'
    (scripts/'launcher.ps1').write_text(source,encoding='utf-8-sig')
    image=root/'截图 with spaces.png'
    result=subprocess.run([str(executable),'--preview','--preview-image',str(image)],cwd=tmp_path,timeout=30)
    value=json.loads((root/'called.json').read_text(encoding='utf-8-sig'))
    assert result.returncode==exit_code and value['console']==0
    assert value['root']==str(scripts) and value['image']==str(image) and value['preview']


@pytest.mark.parametrize('activity_only,executable,receipt',[(False,'Balatro Agent.exe','windows/launcher-build.json'),(True,'Balatro Status.exe','windows/status-build.json')])
def test_public_binary_is_bound_to_its_own_source_and_build_receipt(tmp_path,activity_only,executable,receipt):
    assert verify_launcher(ROOT,activity_only=activity_only)
    for relative in (executable,receipt,'windows/Launcher.cs',
                     'windows/app.manifest','scripts/build_launcher.ps1','pyproject.toml'):
        target=tmp_path/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/relative,target)
    assert verify_launcher(tmp_path,activity_only=activity_only)
    (tmp_path/'windows/Launcher.cs').write_text('changed source')
    assert not verify_launcher(tmp_path,activity_only=activity_only)


@pytest.mark.parametrize('text,stage,expected', [
    ('Uninstalled 6 packages\nExisting Mod/injector installation is preserved; first install refused', 4, '已有配置'),
    ('Installed 6 packages\nSetup stopped: python.exe exit 1', 4, '请查看详情中的原因'),
    ('Unresolved or invalid checkpoint', 4, '操作尚未确认'),
    ('Unresolved independent checkpoint (lifecycle: original-launch); Original lifecycle receipt is missing', 4, '旧启动／关闭收据缺失：original-launch'),
    ('Unresolved independent checkpoint (lifecycle: original-close); Query close_game with the original operation_id', 4, '启动／关闭尚未确认：original-close'),
    ('Installed bytes differ from the recorded installation; preserve user changes\nReuse verification stopped; preserve the output, installation and checkpoints.', 0, '已有配置或安装需要核对'),
    ('Unresolved independent checkpoint (executor: original-action); query action_status first', 0, '上一会话的操作尚未确认'),
    ('Independent checkpoint is invalid; preserve it', 0, '上一会话的操作尚未确认'),
    ('The operation timed out', 1, '下载连接超时'),
    ('HTTPS download stalled', 1, '下载连接超时'),
    ('TimeoutError', 4, '本地连接检查超时'),
])
def test_desktop_failure_distinguishes_installed_packages_conflicts_and_actual_timeouts(tmp_path, text, stage, expected):
    if not PS:
        pytest.skip('Windows PowerShell')
    source = (ROOT / 'scripts/launcher.ps1').read_text(encoding='utf-8-sig')
    start = source.index('function Get-PreparationFailureMessage')
    end = source.index('function Show-PreparationError', start)
    helper = tmp_path / 'classify.ps1'
    helper.write_text('. ' + quote(ROOT / 'scripts/localization.ps1') + '\n' + source[start:end] + '\nGet-PreparationFailureMessage ' + quote(text) + f' {stage}\n', encoding='utf-8-sig')
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(helper)], capture_output=True, timeout=20)
    assert result.returncode == 0
    # Redirected Windows PowerShell text uses the native Windows code page.
    output = result.stdout.decode('utf-8', errors='replace')
    if expected not in output:
        output = result.stdout.decode('gbk', errors='replace')
    assert expected in output


@pytest.mark.parametrize('language,expected', [
    ('zh-CN', '已有配置或安装需要核对，请查看详情。'),
    ('en', 'Existing settings or installation need checking. See Details.'),
])
def test_installation_failure_with_preservation_advice_is_not_an_unresolved_action(tmp_path, language, expected):
    if not PS: pytest.skip('Windows PowerShell')
    source = (ROOT / 'scripts/launcher.ps1').read_text(encoding='utf-8-sig')
    start = source.index('function Get-PreparationFailureMessage')
    end = source.index('function Show-PreparationError', start)
    text = 'Installed bytes differ from the recorded installation; preserve user changes\nReuse verification stopped; preserve the output, installation and checkpoints.'
    helper = tmp_path / 'classify.ps1'
    helper.write_text('. ' + quote(ROOT / 'scripts/localization.ps1') + '\n' + source[start:end]
        + '\n[Console]::OutputEncoding=[Text.Encoding]::UTF8\nGet-PreparationFailureMessage '
        + quote(text) + ' 0 ' + quote(language), encoding='utf-8-sig')
    result = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(helper)],
        capture_output=True, timeout=20)
    assert result.returncode == 0 and result.stdout.decode('utf-8-sig').strip() == expected


def run_launcher_helpers(tmp_path, operation):
    if not PS: pytest.skip('Windows PowerShell launcher')
    source = tmp_path / 'launcher-boundary.ps1'
    source.write_text("$ErrorActionPreference='Stop';Set-StrictMode -Version Latest\n"
        + '. ' + quote(ROOT / 'scripts/localization.ps1') + '\n'
        + '$tokens=$null;$errors=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('
        + quote(ROOT / 'scripts/launcher.ps1') + ',[ref]$tokens,[ref]$errors)\n'
        + "if($errors.Count){throw ($errors|Out-String)}\n"
        + '$ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$true) '
        + '| ForEach-Object {Invoke-Expression $_.Extent.Text}\n'
        + "[Console]::OutputEncoding=[Text.Encoding]::UTF8\n" + operation, encoding='utf-8-sig')
    return subprocess.run([PS, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(source)],
        capture_output=True, timeout=20)


def abandonment_receipt(**changes):
    value = {'schema': 'abandon-session-1', 'state': 'COMMITTED', 'safe_to_prepare': True,
        'original_action_state': 'UNKNOWN', 'game_action_submitted': False, 'normal_game_completed': False}
    return dict(value, **changes)


@pytest.mark.parametrize('receipt,exit_code,accepted', [
    (abandonment_receipt(), 0, True),
    (abandonment_receipt(), 8, False),
    (abandonment_receipt(state='PREPARED'), 0, False),
    (abandonment_receipt(schema='automatic-preparation-1'), 0, False),
    (abandonment_receipt(safe_to_prepare=False), 0, False),
    (abandonment_receipt(original_action_state='COMPLETED'), 0, False),
    (abandonment_receipt(game_action_submitted=True), 0, False),
    (abandonment_receipt(normal_game_completed=True), 0, False),
    ({}, 0, False),
    (None, 0, False),
])
def test_launcher_reprepares_only_after_confirmed_abandonment(tmp_path, receipt, exit_code, accepted):
    path = tmp_path / 'abandon.json'
    if receipt is not None: path.write_text(json.dumps(receipt))
    result = run_launcher_helpers(tmp_path,
        "$script:preparedCalled=$false\nfunction Start-Preparation {$script:preparedCalled=$true}\n"
        + "$timer=[pscustomobject]@{};$timer|Add-Member ScriptMethod Stop {}\n"
        + f"$script:process=[pscustomobject]@{{ExitCode={exit_code}}};$script:process|Add-Member ScriptMethod WaitForExit {{}}\n"
        + '$script:abandonReceiptPath=' + quote(path) + '\n'
        + 'try {Complete-AbandonSession} catch {}\n$script:preparedCalled|ConvertTo-Json')
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
    assert json.loads(result.stdout.decode('utf-8-sig')) is accepted


def launcher_controls():
    return """
$script:language='zh-CN';$script:stdoutPath=$null;$script:stderrPath=$null
$script:abandonId=$null;$script:process=$null;$script:abandonError='';$script:prepared=$false
$ink=[pscustomobject]@{}
foreach($name in @('copy','open','retry','restart','deckChoice','stakeChoice')) {
    Set-Variable $name ([pscustomobject]@{Enabled=$false;Visible=$false})
}
$status=[pscustomobject]@{Text='';ForeColor=$null};$detail=[pscustomobject]@{Text=''}
$progress=[pscustomobject]@{Style='';Visible=$true}
$timer=[pscustomobject]@{};$timer|Add-Member ScriptMethod Stop {};$timer|Add-Member ScriptMethod Start {}
"""


@pytest.mark.parametrize('failure', [
    'Unresolved independent checkpoint (executor: lost-action)',
    'Independent checkpoint is invalid; preserve it',
    'Original lifecycle receipt is missing',
    'Preparation stopped.',
])
def test_abandon_button_remains_available_for_every_preparation_failure(tmp_path, failure):
    result = run_launcher_helpers(tmp_path, 'Add-Type -AssemblyName System.Drawing\n' + launcher_controls()
        + 'try {throw ' + quote(failure) + '} catch {Show-PreparationError}\n'
        + '@{restart=$restart.Enabled -and $restart.Visible;retry=$retry.Enabled -and $retry.Visible;'
        + 'oldActionError=$script:desktopError}|ConvertTo-Json')
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
    value = json.loads(result.stdout.decode('utf-8-sig'))
    assert value == {'restart': True, 'retry': True, 'oldActionError': failure}


def test_abandon_retry_reuses_transaction_and_preserves_failure_details(tmp_path):
    runtime = tmp_path / '.venv/Scripts/python.exe'
    runtime.parent.mkdir(parents=True);runtime.write_bytes(b'synthetic runtime')
    result = run_launcher_helpers(tmp_path, 'Add-Type -AssemblyName System.Drawing\n' + launcher_controls()
        + '$root=' + quote(tmp_path) + '\n'
        + "$script:workers=@()\nfunction Start-Process {param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle,$RedirectStandardOutput,$RedirectStandardError,[switch]$PassThru)\n"
        + "$script:workers+=@{arguments=$ArgumentList;stdout=$RedirectStandardOutput;stderr=$RedirectStandardError;window=$WindowStyle}\n"
        + "return [pscustomobject]@{HasExited=$true;Handle=0}}\n"
        + "Start-AbandonSession;$first=$script:abandonId\n"
        + "try {throw 'Close Balatro normally; PID 1234 is still running.'} catch {Show-AbandonSessionError}\n"
        + "$errorKept=$script:abandonError;$canRetry=$restart.Enabled -and $restart.Visible\n"
        + "Start-AbandonSession\n@{idReused=$first -eq $script:abandonId;workers=$script:workers;errorKept=$errorKept;canRetry=$canRetry}|ConvertTo-Json -Depth 5")
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
    value = json.loads(result.stdout.decode('utf-8-sig'))
    assert value['idReused'] and value['canRetry']
    assert value['errorKept'] == 'Close Balatro normally; PID 1234 is still running.'
    assert len(value['workers']) == 2 and value['workers'][0] == value['workers'][1]
    worker = value['workers'][0]
    assert 'abandon-session --apply --output' in worker['arguments'] and worker['window'] == 'Hidden'


def test_abandon_does_not_start_a_second_worker_while_preparation_is_running(tmp_path):
    result = run_launcher_helpers(tmp_path, launcher_controls()
        + "$script:process=[pscustomobject]@{HasExited=$false};$script:startedSecond=$false\n"
        + "function Start-Process {$script:startedSecond=$true}\n"
        + "try {Start-AbandonSession} catch {$message=$_.Exception.Message}\n"
        + "@{started=$script:startedSecond;message=$message}|ConvertTo-Json")
    assert result.returncode == 0, result.stderr.decode('utf-8', errors='replace')
    value = json.loads(result.stdout.decode('utf-8-sig'))
    assert not value['started'] and 'worker is still running' in value['message']
