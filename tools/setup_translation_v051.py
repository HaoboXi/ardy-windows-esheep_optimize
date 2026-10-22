"""Install only an isolated CPU translation environment and a hash-pinned public model.

Run with the existing backend Python. No package in that Python is changed.
This explicitly downloads software/model assets, never prompts or user documents.
"""
import argparse,hashlib,json,os,subprocess,sys,urllib.request,zipfile
from pathlib import Path

MODEL_SHA='62e7af5a3a48b530e47b7b3e5c78c2de79073ecd815750d2bf3ab35b4a67da2d'
REQUIREMENTS=['ctranslate2==4.7.1','sentencepiece==0.2.1','numpy==2.4.6','PyYAML==6.0.3','psutil==7.2.2']

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',default=str(Path(__file__).resolve().parents[1]));p.add_argument('--model-archive',type=Path);args=p.parse_args()
    root=Path(args.project).resolve();folder=root/'translation_cpu_v051';python=folder/'Scripts/python.exe'
    if not (root/'scripts/generate.py').is_file():raise ValueError('Select the existing ARDY backend directory.')
    if not python.exists():subprocess.run([sys.executable,'-m','venv',str(folder)],check=True)
    subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check',*REQUIREMENTS],check=True)
    dest=root/'translation_models';dest.mkdir(exist_ok=True);archive=args.model_archive or dest/'translate-zh_en-1_9.argosmodel'
    if not archive.exists():
        url='https://argos-net.com/v1/translate-zh_en-1_9.argosmodel?download=1'
        temp=archive.with_suffix('.partial')
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=90) as r,temp.open('wb') as f:
            import shutil;shutil.copyfileobj(r,f)
        os.replace(temp,archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=MODEL_SHA:raise ValueError('Model checksum mismatch. No model installed.')
    # Stanza/Torch sentence models are unnecessary: short clauses are segmented
    # deterministically by punctuation in the application, not by an extra NN.
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if name in ['translate-zh_en-1_9/metadata.json','translate-zh_en-1_9/README.md','translate-zh_en-1_9/sentencepiece.model'] or (name.startswith('translate-zh_en-1_9/model/') and not name.endswith('/')):
                z.extract(name,dest)
    config=dict(python=str(python),model=str(dest/'translate-zh_en-1_9'))
    (root/'translation_config.json').write_text(json.dumps(config,indent=2),encoding='utf8')
    print('CPU translator installed separately. Restart the local ARDY backend if it is running.')
if __name__=='__main__':main()
