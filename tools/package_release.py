#!/usr/bin/env python3
"""Export only the submission app, never the surrounding experimental workspace."""
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP = ['.gitignore', 'README.md', 'SOURCES.md', 'AUDIT.md', 'SUBMISSION.md',
       'CODEX_USAGE_LOG.md', 'RESUME_WORK_DONE.md', 'lunar_copilot.py', 'physics.py', 'mission.py',
       'core.py', 'scoring.py', 'model_slot.py', 'inference.py', 'runtime.py', 'telemetry.py',
       'twitch_transport.py', 'twitch_launcher.py', 'start_demo.command',
       'start_twitch.command', 'lunar_hud.html', 'director.html']
RECEIPTS = ['release_suite.json', 'release_async_mlx.json', 'release_browser.json',
            'metal_scoring_candidate.json', 'metal_test_candidate_rejected.json',
            'metal_coda_verification.json', 'metal_winner_candidate.json', 'release_live_twitch.json',
            'release_live_vote.json', 'metal_narration_draft.json', 'release_suite_70.json',
            'reviewer_fixes.json', 'metal_signal_receipt.json']
SECRET = re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{25,}|oauth:[a-z0-9]{25,}|(?:User Access Token|Refresh Token):\s*[a-z0-9]{25,})')


def build(destination=None):
    destination = Path(destination or ROOT.parent / 'release')
    destination.mkdir(parents=True, exist_ok=True)
    paths = [ROOT / name for name in TOP if (ROOT / name).is_file()]
    paths += sorted((ROOT / 'tests').glob('*.py'))
    paths += sorted((ROOT / 'tools').glob('*.py'))
    paths += sorted((ROOT / 'fixtures').glob('*'))
    paths += [ROOT / 'receipts' / name for name in RECEIPTS if (ROOT / 'receipts' / name).is_file()]
    manifest = {'project': 'Artemis CapCom', 'files': [], 'secrets_scan': 'passed',
                'excluded': ['CLI configuration', 'credentials', 'models', 'legacy root project',
                             'experiments', 'bytecode', 'unverified orchestration', 'historical checkpoints']}
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError('Missing or unsafe release file: ' + str(path.relative_to(ROOT)))
        text = path.read_text(encoding='utf-8')
        if SECRET.search(text):
            raise ValueError('Potential secret in: ' + str(path.relative_to(ROOT)))
        manifest['files'].append({'path': str(path.relative_to(ROOT)), 'bytes': path.stat().st_size,
                                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    archive = destination / 'ArtemisCapCom-source.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in paths:
            bundle.write(path, arcname='ArtemisCapCom/' + str(path.relative_to(ROOT)))
        bundle.writestr('ArtemisCapCom/RELEASE_MANIFEST.json', json.dumps(manifest, indent=2)+'\n')
    (destination / 'RELEASE_MANIFEST.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'{archive}: {len(paths)} files; curated source scan passed; {archive.stat().st_size} bytes')
    return archive


if __name__ == '__main__':
    build()
