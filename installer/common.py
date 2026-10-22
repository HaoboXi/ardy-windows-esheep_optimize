"""Owned state, process locking, resumable hash-verified downloads and safe archives."""
import hashlib,json,os,queue,shutil,stat,subprocess,threading,time,urllib.error,urllib.parse,urllib.request,uuid,zipfile
from pathlib import Path,PurePosixPath

class Cancelled(RuntimeError):pass

def digest(path,check=None):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):
            if check:check()
            h.update(block)
    return h.hexdigest()

def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8');os.replace(temp,path)

def read_json(path,maximum=4*1024*1024):
    p=Path(path)
    if p.stat().st_size>maximum:raise ValueError('JSON file exceeds size limit: '+p.name)
    return json.loads(p.read_text(encoding='utf-8-sig'))

def is_reparse(path):
    try:return Path(path).is_symlink() or bool(getattr(Path(path).lstat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024))
    except OSError:return False

def contained(root,path):
    root=Path(root).resolve();raw=Path(path).absolute()
    for parent in [raw,*raw.parents]:
        if parent==root:break
        if is_reparse(parent):raise ValueError('Refusing an installer write/delete through a reparse point: '+str(parent))
    p=raw.resolve()
    if p==root or not p.is_relative_to(root):raise ValueError('Path escapes the owned installation: '+str(p))
    return p

class InstallLock:
    def __init__(self,root):self.path=Path(root)/'.install.lock';self.file=None
    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True);self.file=self.path.open('a+b');self.file.seek(0)
        if self.path.stat().st_size==0:self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt;msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl;fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:self.file.close();raise RuntimeError('Another installation/repair/verification owns this directory.')
        return self
    def __exit__(self,*args):self.file.close()

class InstallationStateManager:
    def __init__(self,root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True);self.path=self.root/'installation_state.json';self.cancel=self.root/'cancel.requested'
        self.data=read_json(self.path) if self.path.exists() else dict(schema='ardy.installation.v1',instance_id=uuid.uuid4().hex,install_root=str(self.root),status='NOT_INSTALLED',owned_files=[],owned_trees=[],completed={},downloaded_bytes=0)
        if self.data.get('schema')!='ardy.installation.v1' or Path(self.data['install_root']).resolve()!=self.root:raise ValueError('Installation state/root mismatch.')
        self.log_path=self.root/'install.log'
    def save(self):atomic_json(self.path,self.data)
    def log(self,message):
        # No environment dumps, shell token strings or credentials in commands.
        with self.log_path.open('a',encoding='utf8') as f:f.write(time.strftime('%Y-%m-%d %H:%M:%S')+' '+str(message)+'\n')
    def update(self,status=None,**fields):
        if status:
            if status!=self.data['status']:self.data.setdefault('history',[]).append(dict(status=status,time=time.time()))
            self.data['status']=status
        self.data.update(fields,updated_at=time.time());self.save()
    def check_cancel(self):
        if self.cancel.exists():raise Cancelled('Installation cancelled. Verified assets and partial downloads retained for resume.')
    def own(self,path,tree=False):
        p=contained(self.root,path);rel=p.relative_to(self.root).as_posix();key='owned_trees' if tree else 'owned_files'
        if tree and p.exists() and rel not in self.data[key]:
            for item in p.rglob('*'):
                if not item.is_file():continue
                sub=item.relative_to(self.root).as_posix()
                if sub not in self.data['owned_files'] and not any(sub.startswith(t+'/') for t in self.data['owned_trees']):raise ValueError('Refusing to adopt a nonempty unowned directory: '+rel)
        if rel not in self.data[key]:self.data[key].append(rel);self.save()
    def step(self,name,action,verify):
        self.check_cancel()
        if self.data['completed'].get(name) and verify():self.log('Verified existing stage: '+name);return
        action()
        if not verify():raise RuntimeError('Stage validation failed: '+name)
        self.data['completed'][name]=True;self.save()

class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if urllib.parse.urlsplit(newurl).scheme!='https':raise ValueError('Download redirect attempted to leave HTTPS.')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

class Downloader:
    def __init__(self,state,test_http=False):self.state=state;self.test_http=test_http
    def fetch(self,asset,path):
        path=contained(self.state.root,path);path.parent.mkdir(parents=True,exist_ok=True);self.state.own(path)
        expected=int(asset['bytes']);sha=asset['sha256']
        if expected<1 or len(sha)!=64:raise ValueError('A pinned size and SHA256 are required before download.')
        if path.is_file() and path.stat().st_size==expected and digest(path,self.state.check_cancel)==sha:
            self.state.data.setdefault('cached_assets',{})[path.relative_to(self.state.root).as_posix()]=expected
            self.state.update(cached_verified_bytes=sum(self.state.data['cached_assets'].values()));return path
        url=asset['url'];parsed=urllib.parse.urlsplit(url)
        if parsed.username or parsed.password or (parsed.scheme!='https' and not (self.test_http and parsed.hostname=='127.0.0.1')):raise ValueError('Only credential-free HTTPS downloads are allowed.')
        temp=path.with_name(path.name+'.partial');self.state.own(temp)
        for attempt in range(3):
            self.state.check_cancel();offset=temp.stat().st_size if temp.exists() else 0
            if offset>=expected:
                if offset==expected and digest(temp,self.state.check_cancel)==sha:os.replace(temp,path);return path
                temp.unlink();offset=0
            try:
                headers={'User-Agent':'Mozilla/5.0'}
                if offset:headers['Range']='bytes='+str(offset)+'-'
                opener=urllib.request.build_opener(HTTPSRedirect())
                with opener.open(urllib.request.Request(url,headers=headers),timeout=60) as response:
                    if offset and response.status==206:
                        if not response.headers.get('Content-Range','').startswith('bytes '+str(offset)+'-'):raise ValueError('Incorrect resume range.')
                    else:offset=0
                    done=offset;last=0.
                    with temp.open('ab' if offset else 'wb') as f:
                        while True:
                            self.state.check_cancel();block=response.read(1024*1024)
                            if not block:break
                            done+=len(block)
                            if done>expected:raise ValueError('Downloaded file exceeds pinned size.')
                            f.write(block);self.state.data['downloaded_bytes']+=len(block)
                            if time.monotonic()-last>.5:
                                last=time.monotonic();self.state.update(current_file=path.name,file_bytes_done=done,file_bytes_total=expected,progress_kind='BYTES')
                if temp.stat().st_size!=expected:raise IOError('Download ended early; partial data retained.')
                if digest(temp,self.state.check_cancel)!=sha:temp.unlink();raise ValueError('SHA256 mismatch; invalid data discarded.')
                os.replace(temp,path);self.state.save();return path
            except Cancelled:raise
            except (OSError,ValueError,urllib.error.URLError) as exc:
                self.state.log('Download retry '+str(attempt+1)+' '+path.name+': '+str(exc))
                if attempt==2:raise
                time.sleep(min(2**attempt,5))
        raise RuntimeError('Download failed')

def extract_zip(archive,destination):
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        if sum(x.file_size for x in z.infolist())>256*1024*1024:raise ValueError('Backend source ZIP exceeds uncompressed size limit.')
        for info in z.infolist():
            p=PurePosixPath(info.filename)
            if p.is_absolute() or '..' in p.parts or chr(92) in info.filename or ':' in info.filename or (info.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe ZIP member.')
            dest=contained(root,root/p)
            if info.is_dir():dest.mkdir(parents=True,exist_ok=True);continue
            dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info) as src,dest.open('wb') as target:shutil.copyfileobj(src,target)

def run(command,state,env=None,cwd=None,timeout=3600):
    state.check_cancel();state.log('Run '+Path(command[0]).name+' '+(' '.join(str(x) for x in command[1:4]) if isinstance(command,list) else 'installer'))
    process=subprocess.Popen(command,env=env,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    lines=queue.Queue()
    def collect():
        for line in process.stdout:lines.put(line.rstrip())
    thread=threading.Thread(target=collect,daemon=True);thread.start();start=time.monotonic()
    try:
        while process.poll() is None or not lines.empty():
            state.check_cancel()
            if time.monotonic()-start>timeout:raise TimeoutError('Installation subprocess timed out.')
            try:
                line=lines.get(timeout=.15)
                if line.startswith('ARDY_INSTALL_PROGRESS '):
                    event=json.loads(line[len('ARDY_INSTALL_PROGRESS '):]);received=max(0,int(event.get('received_bytes',0)));state.data['downloaded_bytes']+=received
                    state.update(current_file=event.get('current_file','model'),file_bytes_done=event.get('file_bytes_done'),file_bytes_total=event.get('file_bytes_total'),progress_kind='BYTES')
                else:state.log(line);state.update(message=line[-300:],progress_kind='STEPS')
            except queue.Empty:pass
        thread.join(timeout=1)
        if process.returncode:raise RuntimeError('Installation subprocess failed with exit code '+str(process.returncode)+'. See install.log.')
    except BaseException:
        if process.poll() is None:
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            else:process.terminate()
            process.wait(timeout=15)
        raise
