"""Download with official huggingface_hub into local_dir, never a second blob cache."""
import argparse,hashlib,json,os
from pathlib import Path

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True);p.add_argument('--kind',required=True);p.add_argument('--directory',required=True);p.add_argument('--cancel',required=True);a=p.parse_args()
    from huggingface_hub import HfApi,hf_hub_download
    from tqdm.auto import tqdm
    info=json.loads(Path(a.manifest).read_text(encoding='utf8'))[a.kind];folder=Path(a.directory);folder.mkdir(parents=True,exist_ok=True)
    actual={x.rfilename:x for x in HfApi().model_info(info['repo_id'],revision=info['revision'],files_metadata=True,token=False).siblings}
    for record in info['files']:
        remote=actual.get(record['path'])
        if remote is None or remote.size!=record['bytes']:raise ValueError('Pinned remote file list/size changed.')
        if remote.lfs and remote.lfs.sha256!=record['sha256']:raise ValueError('Pinned remote SHA256 differs.')
    class Progress(tqdm):
        def update(self,n=1):
            if Path(a.cancel).exists():raise RuntimeError('Model download cancelled; partial data retained.')
            result=super().update(n)
            print('ARDY_INSTALL_PROGRESS '+json.dumps(dict(current_file=self.desc,file_bytes_done=self.n,file_bytes_total=self.total,received_bytes=n)),flush=True)
            return result
    for record in info['files']:
        target=folder/record['path']
        if target.is_file() and target.stat().st_size==record['bytes']:
            h=hashlib.sha256()
            with target.open('rb') as f:
                for block in iter(lambda:f.read(4*1024*1024),b''):
                    if Path(a.cancel).exists():raise RuntimeError('Model download cancelled.')
                    h.update(block)
            if h.hexdigest()==record['sha256']:continue
        hf_hub_download(repo_id=info['repo_id'],revision=info['revision'],filename=record['path'],local_dir=folder,tqdm_class=Progress,token=False)
    print('Official Hugging Face download complete. Parent performs full SHA256 verification.',flush=True)
if __name__=='__main__':main()
