"""Local launch configuration and single-instance locks; stdlib only."""
import hashlib,json,os,secrets,sys
from pathlib import Path
from .model_paths import ModelPathResolver

MODEL='ARDY-Core-RP-20FPS-Horizon40'
def user_runtime():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.cache')))/'ARDYMotionBridge'

class RuntimeConfig:
    def __init__(self,path):
        self.config_path=Path(path).resolve()
        if self.config_path.stat().st_size>16384:raise ValueError('Runtime configuration exceeds 16 KiB.')
        d=json.loads(self.config_path.read_text(encoding='utf-8'))
        if set(d)-{'project_root','python','data_root','port','session_dir','idle_seconds','install_runtime_config'}:raise ValueError('Unknown runtime configuration field.')
        self.project=Path(d['project_root']).resolve();self.python=Path(d['python']).resolve()
        self.data=Path(d['data_root']).resolve();self.port=int(d.get('port',38641));self.session_dir=Path(d.get('session_dir',user_runtime())).resolve()
        self.idle_seconds=int(d.get('idle_seconds',300))
        if not 1024<=self.port<=65535 or not 30<=self.idle_seconds<=3600:raise ValueError('Invalid local port / idle timeout.')
        if not self.python.is_file() or self.python.name.lower() not in ['python.exe','python']:raise FileNotFoundError('Conda Python executable missing: '+str(self.python))
        if not (self.python.parent/'conda-meta').is_dir():raise ValueError('Use the existing independent Conda environment, not Blender Python.')
        if not (self.project/'ardy/model/ardy_model.py').is_file():raise FileNotFoundError('ARDY source missing under '+str(self.project))
        self.paths=ModelPathResolver(self.project,d.get('install_runtime_config')).validate()
        self.runtime_path=self.paths.config_path
        if (Path.home()/'llm2vec-model').exists() and not (self.project/'backend/model_paths.py').is_file():raise ValueError('Legacy backend has a home-folder encoder override; import into v0.6.0 first.')
        self.data.mkdir(parents=True,exist_ok=True);self.session_dir.mkdir(parents=True,exist_ok=True)
        self.key=hashlib.sha256(str(self.project).casefold().encode()).hexdigest()[:16]
        self.session_path=self.session_dir/'session.json'
        self.lock_dir=user_runtime()/'locks'
    def environment(self):
        env=dict(os.environ);prefix=self.python.parent
        env.update(CHECKPOINTS_DIR=str(self.paths.core_model.parent),ARDY_RUNTIME_CONFIG=str(self.runtime_path),ARDY_NF4_MODEL_DIR=str(self.paths.nf4_model),TEXT_ENCODER_MODE='local',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',LOCAL_CACHE='true',CONDA_PREFIX=str(prefix))
        env['PATH']=os.pathsep.join([str(prefix),str(prefix/'Library/bin'),str(prefix/'Scripts'),env.get('PATH','')])
        return env

class ProcessLock:
    def __init__(self,path):self.path=Path(path);self.file=None
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True);self.file=self.path.open('a+b');self.file.seek(0)
        if self.path.stat().st_size==0:self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();raise RuntimeError('ARDY instance/model already owned by another process: '+str(self.path))
        return self
    def __exit__(self,*args):self.file.close()

def atomic_json(path,value):
    path=Path(path);temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');os.replace(temp,path)

def capabilities():
    return dict(schema='ardy.backend.capabilities.v1',version='0.4.0',model=MODEL,fps=20.,nf4=True,double_quantization=True,offload=True,
        num_frames_per_token=4,generation_horizon_frames=40,denoising_steps=10,history_frames=160,trained_context_seconds=10,
        max_duration_seconds=10.,min_duration_seconds=.05,max_queue=16,num_samples=1,
        source_init_history_interface=True,model_conditioned_verified=False,continuity_mode='POST_PROCESS_STITCHED',
        natural_semantic_completion=False,frame_duration_convention='T samples cover T/fps seconds; sample timestamps 0..(T-1)/fps',
        raw_generation='ceil(max_duration*fps to token multiple), at least 4 frames; immutable raw NPZ and separately trimmed NPZ',
        progress='Actual stage + completed diffusion iterations; loading/encoding time has no fabricated percentage')
