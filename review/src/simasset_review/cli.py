import argparse
import json
from pathlib import Path

from .db import Settings, initialize, import_bundle
from .batch import audit, discover
from .bundle import InvalidBundle


def main():
    parser=argparse.ArgumentParser(description='SimAsset 결과 가져오기·조회·판정')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('init-db')
    imp=sub.add_parser('import')
    imp.add_argument('paths',nargs='+',type=Path)
    imp.add_argument('--namespace',required=True)
    imp.add_argument('--origin',required=True,choices=['team_shared','local_reproduction','fixture'])
    imp.add_argument('--recursive',action='store_true')
    check=sub.add_parser('audit',help='DB 입력 전에 예상 실행·파일·ID·단위를 대조합니다.')
    check.add_argument('path',type=Path)
    check.add_argument('--expected',type=Path,help='예상 실행 목록 JSON (schema_version=1)')
    server=sub.add_parser('serve')
    server.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    if args.command=='audit':
        try:
            report=audit(args.path,args.expected)
        except (InvalidBundle,OSError) as e:
            print(json.dumps({'ready_for_import':False,'code':getattr(e,'code','file_io'),
                              'message':str(e)},ensure_ascii=False,indent=2))
            raise SystemExit(2)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        if not report['ready_for_import']: raise SystemExit(2)
        return
    settings=Settings.load()
    if args.command=='init-db':
        initialize(settings); print('로컬 review 스키마 준비 완료')
    elif args.command=='import':
        paths=discover(args.paths,args.recursive)
        results=[]
        for p in paths:
            results.append({'source':str(p),**import_bundle(settings,p,args.namespace,args.origin)})
        print(json.dumps(results,ensure_ascii=False,indent=2))
        if not results or any(x['status'] in ('invalid','conflict') for x in results):
            raise SystemExit(2)
    else:
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(settings),host='127.0.0.1',port=args.port)


if __name__=='__main__': main()
