"""Source, wheels, official Hugging Face model download and CPU translation setup."""
import json,os,shutil,sys
from pathlib import Path
from .common import Downloader,atomic_json,contained,digest,extract_zip,read_json,run
from .environment import capture,python_environment

class BackendDownloader:
    def __init__(self,state):self.state=state
    def prepare(self,descriptor,source=None,reinstall=False):
        target=contained(self.state.root,self.state.root/'backend');rel='backend'
        if target.exists() and rel not in self.state.data['owned_trees']:raise ValueError('Backend destination is not owned. Select a different root.')
        existing=target/'config/release_manifest.json'
        if existing.is_file() and not reinstall:
            manifest=read_json(existing)
            if digest(existing)==descriptor.get('backend_manifest_sha256') and manifest.get('version')==descriptor['version'] and all((target/name).is_file() and digest(target/name)==sha for name,sha in manifest['source_files'].items()):return target
        self.state.own(target,tree=True)
        if source:
            origin=Path(source).resolve()
            if not (origin/'config/release_manifest.json').is_file():raise ValueError('Select the clean release backend source directory, not an arbitrary original clone.')
        else:
            archive=Downloader(self.state).fetch(descriptor['backend_archive'],self.state.root/'cache/backend-'+descriptor['version']+'.zip')
            origin=self.state.root/'cache/backend_source';self.state.own(origin,tree=True);extract_zip(archive,origin)
        manifest=read_json(origin/'config/release_manifest.json')
        if digest(origin/'config/release_manifest.json')!=descriptor['backend_manifest_sha256']:raise ValueError('Release source manifest differs from the pinned deployment descriptor.')
        for name,sha in manifest['source_files'].items():
            src=contained(origin,origin/name)
            if not src.is_file() or digest(src)!=sha:raise ValueError('Backend source hash mismatch: '+name)
            dest=contained(target,target/name);dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists() or digest(dest)!=sha:shutil.copy2(src,dest)
        shutil.copy2(origin/'config/release_manifest.json',target/'config/release_manifest.json')
        self.state.update(backend_root=str(target),backend_version=manifest['version']);return target

class DependencyInstaller:
    def __init__(self,state,backend):self.state=state;self.backend=Path(backend)
    def install(self,python,force=False):
        cache=self.state.root/'cache/wheels';cache.mkdir(parents=True,exist_ok=True);self.state.own(cache,tree=True)
        rows=read_json(self.backend/'config/wheels.json')
        for row in rows:
            self.state.check_cancel()
            if row.get('bundled'):
                src=self.backend/row['bundled']
                if digest(src)!=row['sha256']:raise ValueError('Bundled native/pure wheel checksum mismatch.')
                dest=cache/row['filename'];shutil.copy2(src,dest)
            else:Downloader(self.state).fetch(row,cache/row['filename'])
        lock=cache/'install.lock';lock.write_text('\n'.join(r['name']+'=='+r['version']+' --hash=sha256:'+r['sha256'] for r in rows)+'\n',encoding='utf8')
        command=[str(python),'-I','-m','pip','--isolated','install','--no-index','--find-links',str(cache),'--no-deps','--require-hashes','-r',str(lock)]
        if force:command.append('--force-reinstall')
        run(command,self.state,env=python_environment(python),timeout=1800)
        run([str(python),'-I','-m','pip','check'],self.state,env=python_environment(python),timeout=120)

class ModelDownloader:
    def __init__(self,state,backend,sources):self.state=state;self.backend=Path(backend);self.sources=sources
    def valid(self,folder,kind):
        folder=Path(folder)
        return all((folder/x['path']).is_file() and (folder/x['path']).stat().st_size==x['bytes'] and digest(folder/x['path'])==x['sha256'] for x in self.sources[kind]['files'])
    def ensure(self,python,kind,existing=None):
        info=self.sources[kind];target=self.state.root/('models' if kind=='nf4_model' else 'checkpoints')/info['local_folder']
        if existing:
            folder=Path(existing).resolve()
            if not self.valid(folder,kind):raise ValueError('Selected '+kind+' directory is missing files or differs from the pinned release. No download was forced.')
            self.state.data.setdefault('installed_model_assets',{})[kind]=info['bytes'];self.state.update(installed_model_bytes=sum(self.state.data['installed_model_assets'].values()))
            self.state.log('Reusing verified local '+kind);return folder
        if self.valid(target,kind):return target
        if target.exists() and target.relative_to(self.state.root).as_posix() not in self.state.data['owned_trees']:raise ValueError('Model target contains unowned files. Choose it as an existing model or use another install root.')
        staging=self.state.root/'cache/model-staging'/info['local_folder'];self.state.own(staging,tree=True);self.state.own(target,tree=True)
        # Recover a cancelled promotion without fetching already verified weights.
        for record in info['files']:
            existing_file=target/record['path'];cached_file=staging/record['path']
            if existing_file.is_file() and not cached_file.exists() and existing_file.stat().st_size==record['bytes'] and digest(existing_file,self.state.check_cancel)==record['sha256']:
                cached_file.parent.mkdir(parents=True,exist_ok=True)
                try:os.link(existing_file,cached_file)
                except OSError:shutil.copy2(existing_file,cached_file)
        command=[str(python),'-I',str(self.backend/'installer/model_download_worker.py'),'--manifest',str(self.backend/'config/model_sources.json'),'--kind',kind,'--directory',str(staging),'--cancel',str(self.state.cancel)]
        env=python_environment(python);env.update(HF_HUB_OFFLINE='0',TRANSFORMERS_OFFLINE='0',HF_HUB_DISABLE_XET='1')
        run(command,self.state,env=env,timeout=7200)
        if not self.valid(staging,kind):raise ValueError('Downloaded model failed full size/SHA256 validation. Previous model kept.')
        target.mkdir(parents=True,exist_ok=True)
        for record in info['files']:
            src=staging/record['path'];dest=target/record['path'];dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.is_file() and dest.stat().st_size==record['bytes'] and digest(dest,self.state.check_cancel)==record['sha256']:src.unlink(missing_ok=True)
            else:os.replace(src,dest)
        if not self.valid(target,kind):raise ValueError('Model promotion validation failed.')
        return target

class TranslationInstaller:
    def __init__(self,state,backend,sources):self.state=state;self.backend=Path(backend);self.sources=sources
    def install(self,python,existing=None):
        if existing:
            d=existing if isinstance(existing,dict) else read_json(existing)
            if not Path(d['python']).is_file() or not (Path(d['model'])/'model/model.bin').is_file():raise ValueError('Existing CPU translation configuration is incomplete.')
            for item in self.sources['translation_model'].get('files',[]):
                path=Path(d['model'])/item['path']
                if not path.is_file() or digest(path)!=item['sha256']:raise ValueError('Existing Argos model checksum mismatch: '+item['path'])
            return d
        folder=self.state.root/'translation_cpu_v051';self.state.own(folder,tree=True)
        run([str(python),'-I','-m','venv',str(folder)],self.state,env=python_environment(python),timeout=120)
        exe=folder/'Scripts/python.exe';wheels=read_json(self.backend/'config/translation_wheels.json');cache=self.state.root/'cache/translation-wheels';cache.mkdir(parents=True,exist_ok=True);self.state.own(cache,tree=True)
        for row in wheels:Downloader(self.state).fetch(row,cache/row['filename'])
        lock=cache/'install.lock';lock.write_text('\n'.join(r['name']+'=='+r['version']+' --hash=sha256:'+r['sha256'] for r in wheels)+'\n',encoding='utf8')
        run([str(exe),'-I','-m','pip','--isolated','install','--no-index','--find-links',str(cache),'--no-deps','--require-hashes','-r',str(lock)],self.state,env=python_environment(python),timeout=1200)
        modelroot=self.state.root/'translation_models';self.state.own(modelroot,tree=True)
        archive=Downloader(self.state).fetch(self.sources['translation_model'],modelroot/'translate-zh_en-1_9.argosmodel')
        import zipfile
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                if name in ['translate-zh_en-1_9/metadata.json','translate-zh_en-1_9/README.md','translate-zh_en-1_9/sentencepiece.model'] or (name.startswith('translate-zh_en-1_9/model/') and not name.endswith('/')):
                    # Trusted archive is hash pinned; the allowlist also forbids traversal.
                    contained(modelroot,modelroot/name);z.extract(name,modelroot)
        return dict(python=str(exe),model=str(modelroot/'translate-zh_en-1_9'))
