import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.public_updates import REPOSITORY, WORKFLOW, release_metadata, successful_run


def metadata():
    return {'format': 1, 'repository': REPOSITORY, 'workflow': WORKFLOW,
            'branch': 'main', 'event': 'push', 'commit': 'a' * 40, 'sha256': 'b' * 64, 'run_id': 123}


@pytest.mark.parametrize('key,value', [('repository', 'foreign/repo'), ('branch', 'other'),
    ('event', 'pull_request'), ('workflow', '.github/workflows/other.yml'),
    ('commit', '../escape'), ('sha256', 'wrong'), ('run_id', '123')])
def test_public_release_rejects_foreign_or_untrusted_provenance(key, value):
    release = metadata(); release[key] = value
    with pytest.raises(ValueError):
        release_metadata(release)


def test_only_successful_current_main_push_run_is_eligible():
    release = release_metadata(metadata())
    run = {'conclusion': 'success', 'status': 'completed', 'event': 'push', 'head_branch': 'main',
           'head_sha': release['commit'], 'path': WORKFLOW, 'head_repository': {'full_name': REPOSITORY}}
    assert successful_run(run, release)
    for changes in ({'conclusion': 'failure'}, {'event': 'pull_request'}, {'head_sha': 'c' * 40},
                    {'status': 'in_progress'}, {'head_repository': {'full_name': 'foreign/repo'}}):
        assert not successful_run(run | changes, release)
