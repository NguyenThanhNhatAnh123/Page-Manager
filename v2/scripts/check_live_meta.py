"""Read-only Meta credential probe; never emits tokens, Page names or Page IDs.

The token is entered through a hidden console prompt and may be cached only as
Fernet ciphertext in the private runtime directory for subsequent local setup.
"""
import argparse
import asyncio
import getpass
import json
import re
from datetime import datetime, timezone
from pathlib import Path
import sys

from cryptography.fernet import Fernet
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / 'meta-page-manager' / 'backend'))
sys.path.insert(0, str(ROOT))
from page_manager.graph import GraphClient, GraphError
from scripts.setup import private
from worker.analytics import METRICS, count, metric_value, social_counts


async def probe(token, version, metrics=False):
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'graph_version': version, 'read_only': True, 'identity_ok': False}
    async with GraphClient(version) as graph:
        try:
            identity = await graph.identity(token)
            identity_id = identity.get('id')
            if not isinstance(identity_id, str) or not identity_id.isdigit():
                return report | {'error': 'invalid_identity'}
            report['identity_ok'] = True
        except GraphError as error:
            return report | {'error': error.status, 'error_code': error.code}
        # Try the bounded System User catalog first, then the User-token edge.
        pages, complete, error = await graph.page_catalog(token, 'system_user', identity_id)
        catalog = 'system_user_assigned_pages'
        if error:
            pages, complete, error = await graph.page_catalog(token, 'user', identity_id)
            catalog = 'user_accounts'
        report.update(catalog=catalog, pages_seen=len({p.get('id') for p in pages if p.get('id')}), catalog_complete=complete)
        if error:
            report.update(catalog_error=error.status, catalog_error_code=error.code)
        # Exercise Page read access, but never inspect or mutate Page content.
        checked = readable = followers_available = 0
        for page in pages[:3]:
            pid = page.get('id')
            if not isinstance(pid, str) or not pid.isdigit():
                continue
            checked += 1
            try:
                details, _ = await graph.details(page.get('access_token') or token, pid)
                if details.get('id') == pid:
                    readable += 1
                    followers_available += type(details.get('followers_count')) is int
            except GraphError:
                pass
        report.update(pages_read_checked=checked, pages_readable=readable, pages_with_follower_count=followers_available)
        if metrics:
            report['metrics'] = await probe_metrics(graph, token, pages)
    return report


async def probe_metrics(graph, token, pages):
    """Bounded sample of the same endpoints used by the analytics worker."""
    result = dict(pages_checked=0, catalogs_readable=0, videos_checked=0,
                  owner_verified=0, views_available=0, comments_available=0,
                  shares_available=0, social_value_shapes=[], errors={})

    def record(error):
        key = f'{error.status}:{error.code or "none"}'
        result['errors'][key] = result['errors'].get(key, 0) + 1

    for page in pages[:11]:
        if result['videos_checked'] >= 3:
            break
        pid = page.get('id')
        if not isinstance(pid, str) or not pid.isdigit():
            continue
        result['pages_checked'] += 1
        try:
            page_token = page.get('access_token') or await graph.page_token(token, pid)
            identity = await graph.identity(page_token)
            if identity.get('id') != pid:
                continue
            catalog = await graph.get(pid + '/videos', page_token, {'fields': 'id', 'limit': 3})
            result['catalogs_readable'] += 1
            for video in catalog.get('data', [])[:3 - result['videos_checked']]:
                vid = video.get('id')
                if not isinstance(vid, str) or not vid.isdigit():
                    continue
                result['videos_checked'] += 1
                owner = await graph.get(vid, page_token, {'fields': 'id,from'})
                if owner.get('id') != vid or (owner.get('from') or {}).get('id') != pid:
                    continue
                result['owner_verified'] += 1
                views = comments = shares = None
                for name in METRICS:
                    try:
                        payload = await graph.get(vid + '/video_insights', page_token, {'metric': name, 'period': 'lifetime'})
                        value = metric_value(payload, name)
                        if name == 'fb_reels_total_plays':
                            views = count(value)
                        else:
                            # Preserve only public schema keys, never metric values.
                            shape = {'type': type(value).__name__}
                            if isinstance(value, dict):
                                shape['keys'] = [key for key in value if isinstance(key, str) and re.fullmatch(r'[A-Za-z_]{1,80}', key)][:12]
                                shape['key_count'] = len(value)
                            if shape not in result['social_value_shapes']:
                                result['social_value_shapes'].append(shape)
                            comments, shares = social_counts(value)
                    except GraphError as error:
                        record(error)
                if comments is None:
                    try:
                        payload = await graph.get(vid + '/comments', page_token, {'limit': 0, 'summary': 'true'})
                        comments = count((payload.get('summary') or {}).get('total_count'))
                    except GraphError as error:
                        record(error)
                result['views_available'] += views is not None
                result['comments_available'] += comments is not None
                result['shares_available'] += shares is not None
        except GraphError as error:
            record(error)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', action='store_true')
    parser.add_argument('--use-cache', action='store_true')
    parser.add_argument('--metrics', action='store_true')
    args = parser.parse_args()
    config = dotenv_values(ROOT / '.env')
    sealed = ROOT / '.runtime' / 'private' / 'live-meta-test.fernet'
    box = Fernet(config['PM_ENCRYPTION_KEY'].encode())
    if args.use_cache:
        token = box.decrypt(sealed.read_bytes()).decode()
    else:
        token = getpass.getpass('META_TOKEN (hidden): ').strip()
    if not 8 <= len(token) <= 8192 or any(c.isspace() for c in token):
        raise SystemExit('Token format invalid; value was not displayed.')
    report = asyncio.run(probe(token, config.get('PM_GRAPH_VERSION', 'v26.0'), args.metrics))
    if args.cache and report['identity_ok']:
        sealed.parent.mkdir(parents=True, exist_ok=True)
        private(sealed.parent)
        sealed.write_bytes(box.encrypt(token.encode()))
        private(sealed)
        report['credential_cached_encrypted'] = True
    destination = ROOT / '.runtime' / 'live-meta-read-check.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError):
        raise SystemExit('Read-only Meta check could not complete; no credential was printed.') from None
