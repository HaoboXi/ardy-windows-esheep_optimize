"""Independent real runtime validation; READY requires a successful inference probe."""
import argparse,importlib.metadata,json,os,socket,subprocess,sys,time,types,urllib.request
from pathlib import Path
if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]));__package__='installer'
from .common import atomic_json,digest,read_json
from .environment import python_environment

def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime-config',required=True);p.add_argument('--inference',action='store_true');p.add_argument('--result',required=True);a=p.parse_args()
    settings=read_json(a.runtime_config);backend=Path(settings['backend_root']);sys.path.insert(0,str(backend));os.environ['ARDY_RUNTIME_CONFIG']=str(Path(a.runtime_config).resolve())
    from backend.model_paths import ModelPathResolver
    paths=ModelPathResolver(backend,a.runtime_config).validate()
    sources=read_json(backend/'config/model_sources.json')
    for kind,folder in [('nf4_model',paths.nf4_model),('core_model',paths.core_model)]:
        for file in sources[kind]['files']:
            path=folder/file['path']
            if not path.is_file() or path.stat().st_size!=file['bytes'] or digest(path)!=file['sha256']:raise ValueError('Model size/SHA256 mismatch: '+kind+'/'+file['path'])
    expected=read_json(backend/'config/runtime_manifest.json');actual={}
    for name,data in expected['packages'].items():
        version=importlib.metadata.version(data['name']);actual[name]=version
        if version!=data['version']:raise ValueError('Runtime dependency differs: '+name+' '+version+' != '+data['version'])
    import torch,numpy as np,motion_correction
    import motion_correction._motion_correction as native
    native_manifest=read_json(backend/'config/native_wheel_manifest.json')
    if digest(Path(native.__file__))!=native_manifest['native_binary_sha256']:raise ValueError('MotionCorrection native binary SHA256 differs from the verified release.')
    if not settings.get('environment_borrowed',True) and not Path(native.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):raise RuntimeError('Fresh runtime borrowed a native module outside its own prefix.')
    if not torch.cuda.is_available() or torch.__version__!='2.11.0+cu128':raise RuntimeError('Expected working CUDA PyTorch 2.11.0+cu128.')
    from backend.translation_service import TranslationService
    translator=TranslationService(backend,Path(a.result).parent/'translation_cache')
    try:
        translated=translator.translate(dict(text='举起左手，不要举起右手。'))
        if translated['translation_status']!='TRANSLATED' or 'left' not in translated['translated_prompt'] or 'right' not in translated['translated_prompt']:raise RuntimeError('Actual CPU Chinese translation failed.')
    finally:translator.close()
    result=dict(schema='ardy.install_validation.v1',status='VERIFIED_STATIC',models_SHA256=True,packages=actual,python=sys.version,torch=str(torch.__version__),cuda=torch.version.cuda,
        gpu=torch.cuda.get_device_name(),extension=str(Path(motion_correction.__file__).name),native_binary_sha256=digest(Path(native.__file__)),native_within_prefix=Path(native.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()),translation=translated,source_root_verified=True,inference=False)
    import ardy
    if not Path(ardy.__file__).resolve().is_relative_to(backend):raise RuntimeError('A different installed ARDY shadows the selected release source.')
    if a.inference:
        # Use the actual authenticated API and persistent GPU worker; no toy model.
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        folder=Path(a.result).parent;session=folder/'session';data=folder/'jobs';config=folder/'probe_launch.json'
        atomic_json(config,dict(project_root=str(backend),python=sys.executable,data_root=str(data),port=port,session_dir=str(session),idle_seconds=60,install_runtime_config=str(Path(a.runtime_config).resolve())))
        log=(folder/'probe_server.log').open('w',encoding='utf8');process=subprocess.Popen([sys.executable,'-I',str(backend/'backend/server.py'),'--config',str(config)],env=python_environment(sys.executable),stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def request(path,body=None):
            credential=read_json(session/'session.json');raw=json.dumps(body).encode() if body is not None else None
            req=urllib.request.Request('http://127.0.0.1:'+str(port)+path,data=raw,headers={'Authorization':'Bearer '+credential['token'],'Content-Type':'application/json'})
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=10) as r:return json.load(r)
        try:
            deadline=time.monotonic()+360
            while not (session/'session.json').is_file():
                if process.poll() is not None:raise RuntimeError('Validation backend failed to start. See probe_server.log.')
                if time.monotonic()>deadline:raise TimeoutError('Validation backend startup timed out.')
                time.sleep(.1)
            health=request('/health');t=request('/translate',dict(text='角色向前走三步。'))
            if t['translation_status']!='TRANSLATED':raise RuntimeError('HTTP CPU translation needs review.')
            job=request('/generate',dict(prompt=t['translated_prompt'],max_duration_seconds=1.,seed=10600))
            while job['status'] not in ['DONE','FAILED','CANCELLED']:
                if time.monotonic()>deadline:raise TimeoutError('Real NF4 inference verification timed out.')
                time.sleep(.25);job=request('/jobs/'+job['job_id'])
            if job['status']!='DONE':raise RuntimeError('Real NF4 probe failed: '+json.dumps(job.get('error',{}),ensure_ascii=False))
            from protocol.motion import load_motion
            motion=load_motion(data/job['job_id']/'motion.npz')
            if motion['frames']!=20 or motion['posed_joints'].shape!=(20,27,3):raise ValueError('Core27 NPZ protocol differs.')
            result.update(status='PASS',inference=True,frames=20,translated_prompt=t['translated_prompt'],generation_metrics=job['metrics'],NPZ_sha256=job['duration']['sha256'],HTTP=True,
                native_postprocess=True,actual_nf4_linear_layers=job['metrics']['actual_nf4_linear_layers'])
        finally:
            try:request('/shutdown',{})
            except Exception:pass
            try:process.wait(timeout=20)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
            log.close()
    atomic_json(a.result,result)
    print('Installation verification '+result['status'],flush=True)
if __name__=='__main__':main()
