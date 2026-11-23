"""Read-only deployment preflight and fingerprints; never provision or reset a database."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from dotenv import dotenv_values
import psycopg
from psycopg import sql


def validate_settings(config, release, previous):
    values = dict(dotenv_values(config))
    if (values.get('PM_NATIVE_SERVER') != '1'
            or values.get('PM_LISTEN') != '127.0.0.1:8020'
            or values.get('PM_WORKER_URL') != 'http://127.0.0.1:8021'
            or urlsplit(values.get('DATABASE_URL', '')).hostname not in {'127.0.0.1', 'localhost', '::1'}
            or not values.get('PM_ENCRYPTION_KEY') or not values.get('PM_INTERNAL_KEY')):
        raise ValueError('An existing native server configuration is required')
    media = Path(values['PM_DATA_DIR']).resolve()
    if not media.is_dir():
        raise ValueError('Existing media directory is required')
    videos=None
    if values.get('PM_VIDEO_DIR'):
        videos=Path(values['PM_VIDEO_DIR'])
        if (not videos.is_absolute() or not videos.is_dir() or
                any(path.is_symlink() or path.is_junction() for path in (videos,*videos.parents))):
            raise ValueError('Existing private video directory is required')
        videos=videos.resolve()
    for root in (release, previous):
        if media.is_relative_to(Path(root).resolve().parent) or videos and videos.is_relative_to(Path(root).resolve().parent):
            raise ValueError('Operational data must be outside all code releases')
    # Automatic updates deliberately exclude schema migrations, including deletions.
    def migrations(root):
        root = Path(root)
        paths = [path for path in root.joinpath('migrations').rglob('*') if path.is_file()]
        paths += [root / 'scripts/provision.py',
                  root.parent / 'meta-page-manager/backend/page_manager/store.py',
                  root.parent / 'meta-page-manager/backend/page_manager/postgres.py']
        return {path.relative_to(root.parent).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths}
    old, new = migrations(previous), migrations(release)
    if not old or old != new:
        raise ValueError('Migration changes require a separate reviewed database deployment')
    return values


def snapshot(config, *, drained=False):
    values = dict(dotenv_values(config))
    if drained and not (values.get('PM_VIDEO_MAINTENANCE_FILE') and Path(values['PM_VIDEO_MAINTENANCE_FILE']).is_file()):
        raise ValueError('Reviewed deployment requires the maintenance marker throughout verification')
    with psycopg.connect(values['DATABASE_URL'], prepare_threshold=None) as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        version = int(db.execute('SHOW server_version_num').fetchone()[0])
        if version // 10000 != 18:
            raise ValueError('Deployment requires PostgreSQL major 18')
        users = db.execute('SELECT id,username,password_hash,role,must_change,active FROM public.pm_users ORDER BY id').fetchall()
        if len(users) != 20:
            raise ValueError('Expected the restored 20-account installation')
        result = {'users': users, 'completed': {}, 'assets': {}, 'bindings': {}}
        if drained:result['all_jobs']={}
        result['mcp'] = db.execute('SELECT id,user_id,digest,can_write,expires_at,revoked_at FROM public.pm_mcp_tokens ORDER BY id').fetchall()
        for user in users:
            owner = str(user[0])
            if not re.fullmatch(r'[0-9a-f-]{36}', owner):
                raise ValueError('Invalid workspace UUID')
            namespace = sql.Identifier('w_' + owner.replace('-', ''))
            # Entire completed rows include request IDs, checkpoints and video IDs.
            result['completed'][owner] = [row[0] for row in db.execute(sql.SQL(
                "SELECT row_to_json(j)::text FROM {}.reel_jobs j WHERE status='completed' ORDER BY id"
            ).format(namespace)).fetchall()]
            if drained:
                result['all_jobs'][owner]=[row[0] for row in db.execute(sql.SQL(
                    'SELECT row_to_json(j)::text FROM {}.reel_jobs j ORDER BY id'
                ).format(namespace)).fetchall()]
            result['assets'][owner] = [row[0] for row in db.execute(sql.SQL(
                'SELECT row_to_json(a)::text FROM {}.reel_assets a ORDER BY id'
            ).format(namespace)).fetchall()]
            result['bindings'][owner] = {
                'pages': db.execute(sql.SQL('SELECT id FROM {}.pages ORDER BY id').format(namespace)).fetchall(),
                'connections': db.execute(sql.SQL(
                    'SELECT id,encrypted_token,token_revision FROM {}.connections ORDER BY id'
                ).format(namespace)).fetchall(),
            }
            active = db.execute(sql.SQL(
                "SELECT COUNT(*) FROM {}.reel_jobs WHERE status NOT IN ('completed','cancelled','failed')"
            ).format(namespace)).fetchone()[0]
            if active and not drained:
                raise ValueError('Active or unresolved Reel jobs: postpone automatic deployment')
            if drained and db.execute(sql.SQL(
                "SELECT COUNT(*) FROM {}.reel_jobs WHERE status IN ('starting','uploading','processing','publishing','verifying')"
            ).format(namespace)).fetchone()[0]:
                raise ValueError('Network Reel operation still active; do not stop or deploy')
    return {'format': 1, 'fingerprint': hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest(),
            'config_sha256': hashlib.sha256(Path(config).read_bytes()).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--release', type=Path)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--write', type=Path)
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--drained', action='store_true', help='Operator-only: maintenance marker and zero active network jobs required')
    args = parser.parse_args()
    if args.release and args.previous:
        validate_settings(args.config, args.release, args.previous)
    current = snapshot(args.config,drained=args.drained)
    if args.write:
        with args.write.open('x', encoding='utf-8') as stream:
            json.dump(current, stream)
    if args.compare and json.loads(args.compare.read_text(encoding='utf-8')) != current:
        raise ValueError('Deployment changed preserved account/Reel/asset/configuration state')
    print('Deployment state verified; account, completed Reel, asset and configuration fingerprints preserved.')
