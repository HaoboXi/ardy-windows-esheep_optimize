"""Small authenticated health CLI; no model imports."""
import argparse,json,urllib.request
from pathlib import Path
def main():
    p=argparse.ArgumentParser();p.add_argument('session');a=p.parse_args();s=json.loads(Path(a.session).read_text(encoding='utf8'))
    if s['host']!='127.0.0.1':raise ValueError('Loopback only.')
    req=urllib.request.Request(f"http://127.0.0.1:{int(s['port'])}/health",headers={'Authorization':'Bearer '+s['token']})
    with urllib.request.urlopen(req,timeout=3) as r:print(r.read().decode())
if __name__=='__main__':main()
