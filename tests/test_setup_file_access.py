"""Synthetic bootstrap file failures; no installer, network or game action."""
import pytest

from test_setup import run_helpers, quote


@pytest.mark.parametrize('winerror', [32, 33])
def test_bootstrap_retries_only_transient_file_access(tmp_path, winerror):
    operation = f"$script:calls=0; Invoke-BoundedFileAccess {{ $script:calls++; if($script:calls -eq 1){{ throw [IO.IOException]::new('synthetic', -2147024896 + {winerror}) }} }}; $script:calls"
    result = run_helpers(tmp_path, {}, operation)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '2'


@pytest.mark.parametrize('winerror,expected', [(32, 4), (33, 4), (5, 1), (112, 1)])
def test_bootstrap_failure_budget_never_changes_permissions(tmp_path, winerror, expected):
    operation = f"$script:calls=0; try {{ Invoke-BoundedFileAccess {{ $script:calls++; throw [IO.IOException]::new('synthetic', -2147024896 + {winerror}) }} }} catch {{ $script:calls }}"
    result = run_helpers(tmp_path, {}, operation)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(expected)


def test_bootstrap_missing_prepared_source_preserves_uncertainty(tmp_path):
    missing = tmp_path / 'missing.tmp'
    operation = "$script:calls=0; try { Invoke-BoundedFileAccess { $script:calls++; throw [IO.IOException]::new('synthetic', -2147024864) } " + quote(missing) + " } catch { $script:calls }"
    result = run_helpers(tmp_path, {}, operation)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '1'


def test_bootstrap_access_denial_retries_only_the_existing_prepared_file(tmp_path):
    prepared = tmp_path / 'prepared.tmp'
    prepared.write_bytes(b'unchanged prepared bytes')
    operation = "$script:calls=0; try { Invoke-BoundedFileAccess { $script:calls++; throw [IO.IOException]::new('synthetic', -2147024891) } " + quote(prepared) + " } catch { $script:calls }"
    result = run_helpers(tmp_path, {}, operation)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '4' and prepared.read_bytes() == b'unchanged prepared bytes'
