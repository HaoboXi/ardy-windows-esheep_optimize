"""Windows preflight and explicit-prefix Conda. Never activate or change global PATH."""
import ctypes,json,os,platform,re,shutil,subprocess,sys
from pathlib import Path
from .common import run,read_json,contained,Downloader

def capture(args,timeout=30):
    return subprocess.check_output(args,text=True,encoding='utf8',errors='replace',timeout=timeout,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

class EnvironmentDetector:
    def detect(self,root):
        root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
        if sys.platform!='win32' or platform.machine().lower() not in ['amd64','x86_64']:raise RuntimeError('Only native Windows x64 is supported.')
        if not ctypes.windll.kernel32.IsProcessorFeaturePresent(39):raise RuntimeError('The verified MotionCorrection wheel requires CPU AVX support.')
        try:
            text=capture(['nvidia-smi','--query-gpu=name,memory.total,memory.free,driver_version','--format=csv,noheader,nounits'])
            name,total,free,driver=[x.strip() for x in text.splitlines()[0].split(',')]
        except (OSError,subprocess.SubprocessError,IndexError,ValueError) as exc:raise RuntimeError('NVIDIA driver/nvidia-smi unavailable. Install a supported NVIDIA driver first.') from exc
        capability=capture(['nvidia-smi']);match=re.search(r'CUDA(?:\s+UMD)?\s+Version:\s*([\d.]+)',capability)
        if not match or tuple(map(int,match[1].split('.'))) < (12,8):raise RuntimeError('The verified cu128 runtime requires driver CUDA capability >=12.8. No CPU/precision fallback is enabled.')
        if float(total)<8*1024:raise RuntimeError('This NF4 deployment requires at least 8 GiB VRAM; 12 GiB RTX 5070 Ti Laptop is the tested target.')
        if float(free)<5.75*1024:raise RuntimeError('Insufficient free GPU memory for verified NF4 loading; close competing GPU applications and retry.')
        return dict(platform='Windows x64',gpu=name,total_vram_MiB=float(total),free_vram_MiB=float(free),driver=driver,driver_cuda=match[1],
            disk_free_bytes=shutil.disk_usage(root).free,verified_gpu=('5070 Ti Laptop' in name),note='Other NVIDIA cards require actual Torch/bitsandbytes inference validation; no blanket compatibility claim.')
    def conda_candidates(self,explicit=None):
        candidates=[]
        if explicit:candidates.append(Path(explicit))
        for key in ['CONDA_EXE','CONDA_PREFIX']:
            if os.environ.get(key):candidates.append(Path(os.environ[key]))
        path=shutil.which('conda')
        if path:candidates.append(Path(path))
        home=Path.home();local=Path(os.environ.get('LOCALAPPDATA',home))
        candidates += [home/n for n in ['miniforge3','miniconda3','anaconda3','Miniforge3','Miniconda3','Anaconda3']]
        candidates += [local/n for n in ['miniforge3','miniconda3','anaconda3']]
        found=[]
        for p in candidates:
            options=[p] if p.name.lower() in ['conda.exe','_conda.exe'] else []
            for base in [p,p.parent,p.parent.parent,p.parent.parent.parent]:options += [base/'Scripts/conda.exe',base/'_conda.exe']
            for exe in options:
                if exe.is_file() and exe not in found:found.append(exe)
        return found
    def find_conda(self,explicit=None):
        for exe in self.conda_candidates(explicit):
            try:
                d=json.loads(capture([str(exe),'info','--json']));return dict(executable=str(exe),root_prefix=d['root_prefix'],version=d['conda_version'])
            except (ValueError,KeyError,OSError,subprocess.SubprocessError):pass
        return None

class CondaManager:
    def __init__(self,state,sources):self.state=state;self.sources=sources;self.detect=EnvironmentDetector()
    def ensure(self,explicit=None,force_private=False):
        existing=None if force_private else self.detect.find_conda(explicit)
        if existing and int(existing['version'].split('.')[0])<25:existing=None
        if existing:self.state.update(conda=existing);return Path(existing['executable'])
        directory=contained(self.state.root,self.state.root/'conda')
        exe=directory/'Scripts/conda.exe'
        if exe.is_file() and 'conda' in self.state.data['owned_trees']:return exe
        if directory.exists() and any(directory.iterdir()) and 'conda' not in self.state.data['owned_trees']:raise ValueError('Conda bootstrap directory is not owned; choose another install root.')
        # NSIS /D handling and several Conda launchers are not reliably Unicode-safe.
        if not str(directory).isascii() or any(c in str(directory) for c in ['\r','\n','"']):raise ValueError('Private Miniforge bootstrap requires an ASCII path. Select an ASCII install root or reuse an existing Conda; backend/model paths may contain Unicode.')
        asset=self.sources['miniforge'];archive=Downloader(self.state).fetch(asset,self.state.root/'cache'/Path(asset['url']).name)
        self.state.own(directory,tree=True)
        command='"'+str(archive)+'" /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /NoRegistry=1 /NoShortcuts=1 /S /D='+str(directory)
        run(command,self.state,timeout=900)
        if not exe.is_file():raise RuntimeError('Miniforge did not create conda.exe. See install.log; retry Repair.')
        info=json.loads(capture([str(exe),'info','--json']));self.state.update(conda=dict(executable=str(exe),root_prefix=info['root_prefix'],version=info['conda_version'],owned=True));return exe
    def create(self,conda):
        prefix=contained(self.state.root,self.state.root/'envs/ardy-runtime');rel=prefix.relative_to(self.state.root).as_posix()
        if prefix.exists() and rel not in self.state.data['owned_trees']:raise ValueError('Runtime prefix already exists and is not owned. Import it explicitly or choose a new root.')
        self.state.own(prefix,tree=True)
        python=prefix/'python.exe'
        if python.is_file():
            try:
                version=json.loads(capture([str(python),'-I','-c','import sys,json,ssl,pip,ctypes;print(json.dumps(list(sys.version_info[:3])))']))
                if version[:2]==[3,11]:return python
            except (OSError,ValueError,subprocess.SubprocessError):pass
        env=dict(os.environ);env['CONDA_PKGS_DIRS']=str(self.state.root/'cache/conda-pkgs');self.state.own(self.state.root/'cache',tree=True)
        env.update(CONDA_SSL_VERIFY='true',PYTHONUTF8='1')
        backend=Path(self.state.data.get('backend_root',Path(__file__).resolve().parents[1]));manifest=backend/'config/conda_packages.json'
        if not manifest.is_file():raise ValueError('Verified explicit Conda Python manifest is missing; use the complete release.')
        packages=read_json(manifest);cache=self.state.root/'cache/conda-archives';cache.mkdir(parents=True,exist_ok=True);self.state.own(cache,tree=True)
        for row in packages:
            candidates=[self.state.root/'cache/conda-pkgs'/row['filename']]
            if self.state.data.get('conda',{}).get('root_prefix'):candidates.append(Path(self.state.data['conda']['root_prefix'])/'pkgs'/row['filename'])
            target=cache/row['filename']
            for cached in candidates:
                if target.exists():break
                if not cached.is_file():continue
                from .common import digest
                if digest(cached,self.state.check_cancel)==row['sha256']:
                    try:os.link(cached,target)
                    except OSError:shutil.copy2(cached,target)
            Downloader(self.state).fetch(row,target)
        lock=cache/'python.explicit';lock.write_text('@EXPLICIT\n'+'\n'.join((cache/r['filename']).as_uri()+'#'+r['sha256'] for r in packages)+'\n',encoding='ascii')
        # Conda explicit installs can treat a recorded-but-missing Python binary
        # as satisfied even with --force-reinstall. Preserve the broken owned
        # prefix, then create a truly new prefix from verified cached packages.
        if prefix.exists() and any(prefix.iterdir()):
            import time
            backup=contained(self.state.root,prefix.with_name('ardy-runtime-interrupted-'+str(time.time_ns())))
            self.state.own(backup,tree=True);prefix.rename(backup);self.state.log('Preserved interrupted Python prefix at '+str(backup))
        command=[str(conda),'create','--yes','--prefix',str(prefix),'--file',str(lock),'--offline','--no-default-packages','--no-shortcuts']
        run(command,self.state,env=env,timeout=900)
        if not python.is_file():raise RuntimeError('Conda environment was not created.')
        return python

def python_environment(python):
    exe=Path(python).resolve();env=dict(os.environ)
    windows=Path(os.environ.get('SystemRoot','C:/Windows'));nvidia=shutil.which('nvidia-smi')
    env['PATH']=os.pathsep.join([str(exe.parent),str(exe.parent/'Library/bin'),str(exe.parent/'Scripts'),str(windows/'System32'),str(windows),str(windows/'System32/Wbem')]+([str(Path(nvidia).parent)] if nvidia else []))
    env.update(PIP_DISABLE_PIP_VERSION_CHECK='1',PYTHONUTF8='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    return env
