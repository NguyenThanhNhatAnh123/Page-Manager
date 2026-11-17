"""Plan a Drive archive or record a downloaded, byte-verified Drive copy."""
import argparse
from http.cookiejar import CookieJar
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
sys.path.insert(0,str(ROOT.parent/'via-auth'))

from page_manager.reel_archive import DRIVE_FOLDER, ReelArchive
from page_manager.store import Store
from via_auth.client import local_opener


def live_api(path):
    base = 'http://127.0.0.1:8000/pages'
    opener = local_opener(HTTPCookieProcessor(CookieJar()))
    with opener.open(base+'/api/session',timeout=10) as response:
        response.read()
    with opener.open(base+path,timeout=10) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    commands.add_parser('plan')
    commands.add_parser('check-live')
    for command in ('record','prune'):
        action = commands.add_parser(command)
        action.add_argument('--asset-id',required=True)
        action.add_argument('--drive-file-id',required=True)
        action.add_argument('--drive-parent-id',required=True,choices=[DRIVE_FOLDER])
        action.add_argument('--downloaded',required=True,type=Path)
    args = parser.parse_args()
    if args.command=='check-live':
        schema = live_api('/api/v1/openapi.json')
        params = schema['paths']['/api/v1/reels/assets']['get']['parameters']
        if not any(param['name']=='local_only' for param in params):
            parser.error('Page Manager đang chạy bản chưa có hỗ trợ lưu trữ Drive.')
        print('{"archive_api_ready":true}')
        return
    if not (ROOT/'data'/'page-manager.sqlite3').is_file():
        parser.error('Không tìm thấy kho dữ liệu Page Manager.')
    archive = ReelArchive(Store(ROOT))
    if args.command=='plan':
        result = archive.plan()
    else:
        if args.command=='prune':
            query = urlencode({'asset_id':args.asset_id,'limit':1})
            rows = live_api('/api/v1/reels/assets?'+query)['assets']
            expected = f'https://drive.google.com/file/d/{args.drive_file_id}/view'
            if not any(row.get('id')==args.asset_id and row.get('drive_url')==expected
                       and row.get('preview_url') is None for row in rows):
                parser.error('Chưa đọc lại được đúng liên kết Drive trong Via. Tệp cục bộ vẫn được giữ.')
        result = archive.apply(args.asset_id,args.drive_file_id,args.downloaded,prune=args.command=='prune')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':
    main()
