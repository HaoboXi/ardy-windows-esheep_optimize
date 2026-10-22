"""Standalone standard-library bootstrap. Used by PowerShell and Blender's child Python."""
import argparse,json,os,shutil,sys,time
from pathlib import Path
if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]));__package__='installer'
from .common import Cancelled,InstallLock,InstallationStateManager,atomic_json,contained,read_json,run
from .environment import CondaManager,EnvironmentDetector,python_environment,capture
from .resources import BackendDownloader,DependencyInstaller,ModelDownloader,TranslationInstaller
from .planning import DownloadPlanner

def registry_path():return Path(os.environ.get('LOCALAPPDATA',Path.home()/'.cache'))/'ARDYMotionBridge/install_registry.json'

class InstallationValidator:
    def __init__(self,state,backend):self.state=state;self.backend=Path(backend)
    def validate(self,config):
        settings=read_json(config);output=self.state.root/'verification/result.json';self.state.own(output.parent,tree=True)
        run([settings['python'],'-I',str(self.backend/'installer/verify_install.py'),'--runtime-config',str(config),'--inference','--result',str(output)],self.state,env=python_environment(settings['python']),timeout=600)
        result=read_json(output)
        if result.get('status')!='PASS' or not result.get('inference'):raise RuntimeError('Real inference validation did not pass. Installation is not READY.')
        return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--install-root',required=True);p.add_argument('--descriptor',required=True);p.add_argument('--backend-source');p.add_argument('--conda');p.add_argument('--force-private-conda',action='store_true');p.add_argument('--started-at',type=float,default=time.time())
    p.add_argument('--mode',choices=['install','repair','verify','reinstall','import','detect','discover'],default='install');p.add_argument('--existing-project');p.add_argument('--existing-python');p.add_argument('--nf4-directory');p.add_argument('--core-directory');p.add_argument('--translation-config')
    a=p.parse_args();root=Path(a.install_root).resolve();descriptor=read_json(a.descriptor);state=InstallationStateManager(root)
    with InstallLock(root):
        if Path(a.descriptor).resolve().parent==root and Path(a.descriptor).name=='.ardy-bootstrap-descriptor.json':state.own(Path(a.descriptor))
        if state.cancel.exists() and state.cancel.stat().st_mtime<a.started_at:state.cancel.unlink()
        try:
            old_status=state.data['status'];state.update('PREFLIGHT',message='Checking Windows, NVIDIA, free VRAM and disk.',process_id=os.getpid())
            state.check_cancel()
            if a.mode=='discover':
                detected=EnvironmentDetector().find_conda(a.conda);found=[]
                if detected:
                    envs=json.loads(capture([detected['executable'],'env','list','--json'])).get('envs',[])
                    probe='import importlib.metadata,json;from urllib.request import url2pathname;from urllib.parse import urlsplit;from pathlib import Path;d=importlib.metadata.distribution("ardy");u=json.loads(d.read_text("direct_url.json"))["url"];print(json.dumps({"project":url2pathname(urlsplit(u).path)}))'
                    for prefix in envs[:32]:
                        python=Path(prefix)/'python.exe'
                        if not python.is_file():continue
                        try:
                            row=json.loads(capture([str(python),'-I','-c',probe],timeout=10))
                            if (Path(row['project'])/'scripts/generate.py').is_file():found.append(dict(row,python=str(python)))
                        except Exception as exc:state.log('Environment discovery skipped '+python.parent.name+': '+type(exc).__name__)
                state.update(old_status if old_status=='READY' else 'NOT_INSTALLED',discovered_environments=found,message='Found '+str(len(found))+' existing ARDY environment(s). Select Import Existing to validate and reuse.');return
            machine=EnvironmentDetector().detect(root);state.update(machine=machine)
            if a.mode=='verify':
                cfg=root/'runtime_config.json';settings=read_json(cfg);state.update('VERIFYING');InstallationValidator(state,settings['backend_root']).validate(cfg)
                state.update('READY',message='Real inference verification passed.',actual_needed_download_bytes=0,verified_at=time.time())
                atomic_json(registry_path(),dict(schema='ardy.install_registry.v1',install_root=str(root),runtime_config=str(cfg),version='0.6.0'));return
            sources=descriptor['model_sources'];importing=a.mode=='import';state.update(message='Checking cached files and selected model SHA256; no model download in this step.')
            plan=DownloadPlanner(state,descriptor).build(a)
            # Imported models/envs are borrowed, never added to owned trees.
            if machine['disk_free_bytes']<(2*2**30 if importing else plan['recommended_free_bytes']):raise RuntimeError('Insufficient disk space. Recommended free space: '+str(plan['recommended_free_bytes']//2**30)+' GiB.')
            if a.mode=='detect':state.update('NOT_INSTALLED',message='Preflight passed. Installation has not run.');return
            state.update('DOWNLOADING_BACKEND',message='Preparing verified release source.')
            backend=BackendDownloader(state).prepare(descriptor,a.backend_source,a.mode=='reinstall')
            previous=read_json(root/'runtime_config.json') if (root/'runtime_config.json').is_file() else {}
            if importing:
                if not a.existing_project or not a.existing_python:raise ValueError('Select the existing ARDY source and Conda Python for import.')
                python=Path(a.existing_python).resolve()
                if not python.is_file() or not (python.parent/'conda-meta').is_dir():raise ValueError('Selected existing Conda Python is invalid.')
                old=Path(a.existing_project).resolve()
                if not (old/'scripts/generate.py').is_file():raise ValueError('Existing ARDY source not found.')
                from_path=old/'models/Esheep-ardy-llm2vec_NF4';nf4=a.nf4_directory or str(from_path if from_path.is_dir() else old/'models/KIMODO-Meta3_llm2vec_NF4')
                core=a.core_directory or str(old/'checkpoints/ARDY-Core-RP-20FPS-Horizon40');translation_config=a.translation_config or str(old/'translation_config.json')
                state.update(environment_borrowed=True,python=str(python),message='Reusing existing environment and verified weights; no pip/Conda upgrades.')
            else:
                state.update('CREATING_ENV');manager=CondaManager(state,sources);conda=manager.ensure(a.conda,a.force_private_conda);python=manager.create(conda)
                state.update('INSTALLING_DEPENDENCIES');DependencyInstaller(state,backend).install(python,force=a.mode=='repair')
                nf4=a.nf4_directory or previous.get('models',{}).get('nf4');core=a.core_directory or previous.get('models',{}).get('core');translation_config=a.translation_config or previous.get('translation')
                state.update(environment_borrowed=False)
            state.update('DOWNLOADING_MODELS',message='Validating/reusing existing weights or downloading pinned revisions.')
            models=ModelDownloader(state,backend,sources);nf4=models.ensure(python,'nf4_model',nf4);core=models.ensure(python,'core_model',core)
            state.update('INSTALLING_TRANSLATION');translation=TranslationInstaller(state,backend,sources).install(python,translation_config)
            runtime=dict(schema='ardy.runtime.v1',version='0.6.0',instance_id=state.data['instance_id'],install_root=str(root),backend_root=str(backend),python=str(python),environment_borrowed=importing,
                models=dict(nf4=str(nf4),core=str(core)),translation=translation,model_revisions={k:sources[k]['revision'] for k in ['nf4_model','core_model']})
            config=root/'runtime_config.json';state.own(config);atomic_json(config,runtime)
            state.update('VERIFYING',message='Validating exact packages, DLLs, model hashes, CPU translation, HTTP and real NF4/Core27 inference.')
            verification=InstallationValidator(state,backend).validate(config)
            logical=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
            state.update('READY',runtime_config=str(config),python=str(python),backend_root=str(backend),backend_version='0.6.0',message='Environment Ready: actual CPU translation and NF4/Core27 inference passed.',verified_at=time.time(),
                actual_needed_download_bytes=0,owned_root_logical_bytes=logical,verification=dict(status=verification['status'],inference=True,frames=verification['frames']))
            atomic_json(registry_path(),dict(schema='ardy.install_registry.v1',install_root=str(root),runtime_config=str(config),version='0.6.0'))
        except Cancelled as exc:state.update('CANCELLED',message=str(exc));raise SystemExit(2)
        except Exception as exc:state.update('REPAIR_REQUIRED' if (root/'runtime_config.json').exists() else 'FAILED',message=type(exc).__name__+': '+str(exc));state.log(state.data['message']);raise
if __name__=='__main__':main()
