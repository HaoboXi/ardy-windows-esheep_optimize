"""Replaceable, local-only CPU translator. Heavy libraries live in an isolated child."""
import collections,hashlib,json,os,queue,subprocess,threading,time
from pathlib import Path

class TranslationError(ValueError):pass

class TranslationService:
    provider='argos-zh_en-1.9-ct2-int8-v1'
    def __init__(self,project,cache_directory):
        self.project=Path(project);self.directory=Path(cache_directory);self.lock=threading.Lock()
        self.worker=None;self.events=queue.Queue();self.cache=collections.OrderedDict()
        self.revision=hashlib.sha256(b''.join(Path(__file__).with_name(n).read_bytes() for n in ['translation_engine.py','translation_text.py','translation_worker.py'])).hexdigest()
    def paths(self):
        python=self.project/'translation_cpu_v051/Scripts/python.exe';model=self.project/'translation_models/translate-zh_en-1_9'
        runtime=os.environ.get('ARDY_RUNTIME_CONFIG')
        if runtime and Path(runtime).is_file():
            config=json.loads(Path(runtime).read_text(encoding='utf8'));translation=config.get('translation',{})
            if translation.get('python') and translation.get('model'):return Path(translation['python']),Path(translation['model'])
        path=self.project/'translation_config.json'
        if path.exists():
            if path.stat().st_size>16384:raise TranslationError('Translation configuration exceeds 16 KiB.')
            d=json.loads(path.read_text(encoding='utf8'));python=Path(d['python']);model=Path(d['model'])
            if not python.is_absolute() or not model.is_absolute():raise TranslationError('Translation paths must be absolute.')
        return python,model
    def status(self):
        result=dict(provider=self.provider,available=False,device='cpu',isolated=True,
            loaded=self.worker is not None and self.worker.poll() is None,network_translation=False)
        try:
            python,model=self.paths();result['available']=python.is_file() and (model/'model/model.bin').is_file()
        except (OSError,ValueError,TypeError,KeyError) as exc:result['error']='Translation configuration: '+str(exc)
        return result
    def start(self):
        if self.worker is not None and self.worker.poll() is None:return
        python,model=self.paths()
        if not python.is_file() or not (model/'model/model.bin').is_file():
            raise TranslationError('Offline translator is not installed. Run tools/setup_translation_v051.py with the backend Python, or enter confirmed English. No text was sent to ARDY or any online service.')
        env=dict(os.environ);env['CUDA_VISIBLE_DEVICES']='-1';env['OMP_NUM_THREADS']='4'
        self.worker=subprocess.Popen([str(python),'-I',str(Path(__file__).with_name('translation_worker.py')),str(model)],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf8',bufsize=1,
            env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        proc=self.worker;events=queue.Queue();self.events=events
        def read():
            for line in proc.stdout:
                try:events.put(json.loads(line))
                except ValueError:events.put(dict(error='Invalid translator response.'))
            events.put(dict(error='CPU translator exited. Check its separate environment and model.'))
        threading.Thread(target=read,daemon=True).start()
    def translate(self,body):
        if not isinstance(body,dict) or set(body)!={'text'}:raise TranslationError('Translation accepts only a text field.')
        text=body['text']
        if not isinstance(text,str) or not text.strip() or len(text)>2000 or any(ord(c)<32 and c not in '\n\t\r' for c in text):raise TranslationError('Text must contain 1..2000 characters without control codes.')
        if not any('\u3400'<=c<='\u9fff' for c in text):
            return dict(original_prompt=text,translated_prompt=text,translation_provider='passthrough',translation_status='NOT_NEEDED',translation_manually_edited=False,cache_hit=False,milliseconds=0.)
        key=hashlib.sha256((self.provider+'\0'+self.revision+'\0'+text).encode('utf8')).hexdigest();start=time.perf_counter()
        with self.lock:
            if key in self.cache:result=dict(self.cache[key]);result.update(cache_hit=True,milliseconds=(time.perf_counter()-start)*1000);return result
            path=self.directory/(key+'.json')
            if path.is_file() and path.stat().st_size<32768:
                try:
                    result=json.loads(path.read_text(encoding='utf8'))
                    if result['original_prompt']!=text or result['translation_provider']!=self.provider:raise ValueError('Cache identity mismatch')
                    from .translation_text import validate_english
                    validate_english(result['translated_prompt']);self.remember(key,result)
                    return dict(result,cache_hit=True,milliseconds=(time.perf_counter()-start)*1000)
                except (ValueError,KeyError,TypeError):pass
            self.start()
            try:
                self.worker.stdin.write(json.dumps(dict(text=text),ensure_ascii=True)+'\n');self.worker.stdin.flush()
                result=self.events.get(timeout=45)
            except (OSError,queue.Empty) as exc:
                self.close();raise TranslationError('CPU translation timed out or disconnected; generation was not submitted.') from exc
            if result.get('error'):self.close();raise TranslationError(result['error'])
            result.update(original_prompt=text,translation_provider=self.provider,translation_manually_edited=False,cache_hit=False,milliseconds=(time.perf_counter()-start)*1000)
            self.directory.mkdir(parents=True,exist_ok=True);temp=path.with_suffix('.tmp');temp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf8');os.replace(temp,path)
            self.remember(key,result);return result
    def remember(self,key,value):
        self.cache[key]=dict(value)
        while len(self.cache)>512:self.cache.popitem(last=False)
    def close(self):
        if self.worker is not None:
            if self.worker.poll() is None:
                # Windows venv python.exe is a redirector with a real Python
                # child. EOF ends both normally; kill the owned tree on hangs.
                try:self.worker.stdin.close()
                except OSError:pass
                try:self.worker.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if os.name=='nt':subprocess.run(['taskkill','/PID',str(self.worker.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    else:self.worker.kill()
                    self.worker.wait(timeout=3)
            self.worker=None
