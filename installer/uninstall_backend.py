"""Delete only recorded owned paths. Borrowed environments/models are never removed."""
import argparse,os,shutil,sys,json,time,urllib.request
from pathlib import Path
if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]));__package__='installer'
from .common import InstallationStateManager,InstallLock,contained,read_json,is_reparse

class BackendUninstaller:
    def __init__(self,state):self.state=state
    def remove(self,keep_models=True,keep_outputs=True):
        root=self.state.root
        self.stop_backend();self.state.update('REPAIR_REQUIRED',message='Removing only installer-owned runtime paths; requested data retained.')
        def keep(rel):
            first=Path(rel).parts[0]
            return (keep_models and first in ['models','checkpoints','translation_models','cache']) or (keep_outputs and first in ['outputs','verification'])
        # Nothing recursively removes INSTALL_ROOT itself. A junction is unlinked,
        # and every target's resolved path must remain within this owned root.
        for rel in sorted(self.state.data['owned_trees'],key=len,reverse=True):
            if keep(rel):continue
            raw=root/rel
            if is_reparse(raw):
                contained(root,raw.parent/'_ownership_scope_check')
                if os.name=='nt' and raw.is_dir():os.rmdir(raw)
                else:raw.unlink()
                continue
            p=contained(root,raw)
            if not p.exists():continue
            if p.is_dir():
                if any(x.suffix.lower() in ['.blend','.blend1','.pmx','.pmd'] for x in p.rglob('*') if x.is_file()):raise ValueError('A user character/BLEND file was found inside an owned runtime tree; move it elsewhere before uninstall.')
                shutil.rmtree(p)
        for rel in self.state.data['owned_files']:
            if keep(rel):continue
            p=contained(root,root/rel)
            if p.is_file():p.unlink()
        self.state.update('NOT_INSTALLED',message='Owned runtime removed. Borrowed paths and requested models/outputs retained.')
        registry=Path(os.environ.get('LOCALAPPDATA',Path.home()/'.cache'))/'ARDYMotionBridge/install_registry.json'
        if registry.is_file() and Path(read_json(registry)['install_root']).resolve()==root:registry.unlink()
    def stop_backend(self):
        expected=self.state.data.get('backend_root')
        if not expected:return
        session=Path(os.environ.get('LOCALAPPDATA',Path.home()/'.cache'))/'ARDYMotionBridge/session.json'
        if not session.is_file():return
        data=read_json(session,16384)
        if data.get('host')!='127.0.0.1' or not 1024<=int(data.get('port',0))<=65535:raise ValueError('Invalid local backend session; stop it manually.')
        def request(route,post=False):
            req=urllib.request.Request('http://127.0.0.1:'+str(data['port'])+route,data=b'{}' if post else None,headers={'Authorization':'Bearer '+data['token'],'Content-Type':'application/json'})
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=3) as response:return json.load(response)
        try:health=request('/health')
        except OSError:return
        if Path(health.get('project_root','')).resolve()!=Path(expected).resolve():return
        request('/shutdown',True);deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            try:request('/health');time.sleep(.2)
            except OSError:return
        raise RuntimeError('This backend did not stop; uninstall aborted before deleting runtime files.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--install-root',required=True);p.add_argument('--delete-owned-models',action='store_true');p.add_argument('--delete-owned-outputs',action='store_true');p.add_argument('--confirm',action='store_true');a=p.parse_args()
    if not a.confirm:raise SystemExit('Uninstall requires explicit --confirm. Models/output are retained unless their separate deletion flags are set.')
    state=InstallationStateManager(a.install_root)
    with InstallLock(state.root):BackendUninstaller(state).remove(not a.delete_owned_models,not a.delete_owned_outputs)
if __name__=='__main__':main()
