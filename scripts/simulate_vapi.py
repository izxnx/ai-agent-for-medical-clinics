import argparse
import json
import os
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=ROOT/'tests'/'fixtures'
def load_env():
    env=ROOT/'.env'
    values={}
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,value=line.split('=',1); values[key.strip()]=value.strip().strip('"')
    return values

def main():
    parser=argparse.ArgumentParser(description='Надіслати вигаданий webhook-сценарій локальному бекенду.')
    parser.add_argument('kind',choices=['tool','end-of-call','all'])
    parser.add_argument('--scenario',help='Ім’я JSON fixture без .json')
    parser.add_argument('--url',default='http://localhost:8000/vapi/webhook')
    args=parser.parse_args()
    env=load_env(); secret=env.get('VAPI_SECRET') or os.getenv('VAPI_SECRET')
    if not secret: parser.error('VAPI_SECRET відсутній у .env')
    files=sorted(FIXTURES.glob('*.json'))
    files=[p for p in files if (args.kind=='all' or (args.kind=='tool' and p.name.startswith('tool_')) or (args.kind=='end-of-call' and p.name.startswith('end_call_')))]
    if args.scenario:
        files=[p for p in files if p.stem==args.scenario]
        if not files: parser.error('Сценарій не знайдено у tests/fixtures')
    for path in files:
        request=urllib.request.Request(args.url,data=path.read_bytes(),headers={'Content-Type':'application/json','X-Vapi-Secret':secret},method='POST')
        try:
            with urllib.request.urlopen(request,timeout=15) as response:
                print(f'{path.name}: HTTP {response.status} {response.read().decode("utf-8")}')
        except Exception as exc:
            print(f'{path.name}: {type(exc).__name__}: {exc}')
if __name__=='__main__': main()
