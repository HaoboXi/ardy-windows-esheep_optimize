"""Background verification of known download sizes, cached bytes and borrowed models."""
from pathlib import Path
from .common import digest,read_json
from .environment import EnvironmentDetector

class DownloadPlanner:
    def __init__(self,state,descriptor):self.state=state;self.d=descriptor;self.root=state.root
    def build(self,args):
        d=self.d;sources=d['model_sources'];cached=0;installed=0;need=0;fresh=0
        previous=read_json(self.root/'runtime_config.json') if (self.root/'runtime_config.json').is_file() else {}
        importing=args.mode=='import'
        def asset(row,path):
            nonlocal cached,need,fresh
            self.state.check_cancel()
            fresh+=row['bytes'];p=Path(path)
            if p.is_file() and p.stat().st_size==row['bytes'] and digest(p,self.state.check_cancel)==row['sha256']:cached+=row['bytes']
            else:need+=row['bytes']
        if not args.backend_source:asset(d['backend_archive'],self.root/'cache'/('backend-'+d['version']+'.zip'))
        if not importing:
            private_exists=(self.root/'conda/Scripts/conda.exe').is_file()
            conda=EnvironmentDetector().find_conda(args.conda) if not args.force_private_conda else None
            if not private_exists and not conda:asset(sources['miniforge'],self.root/'cache'/Path(sources['miniforge']['url']).name)
            if not (self.root/'envs/ardy-runtime/python.exe').is_file():
                for row in d.get('conda_packages',[]):asset(row,self.root/'cache/conda-archives'/row['filename'])
            for row in d.get('runtime_wheels',[]):
                if not row.get('bundled'):asset(row,self.root/'cache/wheels'/row['filename'])
        for kind,argument,parent in [('nf4_model',args.nf4_directory,'models'),('core_model',args.core_directory,'checkpoints')]:
            info=sources[kind];key='nf4' if kind=='nf4_model' else 'core';explicit=argument or previous.get('models',{}).get(key)
            if importing and not explicit and args.existing_project:
                old=Path(args.existing_project)
                if kind=='nf4_model':explicit=old/'models/Esheep-ardy-llm2vec_NF4' if (old/'models/Esheep-ardy-llm2vec_NF4').is_dir() else old/'models/KIMODO-Meta3_llm2vec_NF4'
                else:explicit=old/'checkpoints'/info['local_folder']
            folder=Path(explicit) if explicit else self.root/parent/info['local_folder']
            fresh+=info['bytes']
            valid=all((folder/f['path']).is_file() and (folder/f['path']).stat().st_size==f['bytes'] and digest(folder/f['path'],self.state.check_cancel)==f['sha256'] for f in info['files'])
            if valid:installed+=info['bytes']
            elif explicit:raise ValueError('Selected existing '+kind+' is incomplete or fails SHA256. It will not be silently replaced.')
            else:
                for file in info['files']:
                    stage=self.root/'cache/model-staging'/info['local_folder']/file['path']
                    if stage.is_file() and stage.stat().st_size==file['bytes'] and digest(stage)==file['sha256']:cached+=file['bytes']
                    else:need+=file['bytes']
        borrowed_translation=importing or args.translation_config or previous.get('translation')
        if not borrowed_translation:
            for row in d.get('translation_wheels',[]):asset(row,self.root/'cache/translation-wheels'/row['filename'])
            asset(sources['translation_model'],self.root/'translation_models/translate-zh_en-1_9.argosmodel')
        plan=dict(known_fresh_download_bytes=fresh,actual_needed_download_bytes=need,cached_verified_bytes=cached,installed_model_bytes=installed,
            estimated_download_bytes=need,recommended_free_bytes=(2 if importing else 24)*2**30,installed_bytes_estimate=15*2**30,
            estimate_note='Pinned artifact payload bytes after full cache/model SHA256 verification. HTTP/metadata overhead is excluded; Miniforge may supply reusable Conda artifacts; unverified partial bytes are not counted as verified cache.')
        self.state.update(download_plan=plan,cached_verified_bytes=cached,installed_model_bytes=installed)
        return plan
