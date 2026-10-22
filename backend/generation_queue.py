"""Single owned GPU worker; pending/running cancellation and durable job history."""
import collections,json,math,os,queue,re,subprocess,threading,time,uuid
from pathlib import Path
from .runtime_config import atomic_json,capabilities

FINAL={'DONE','FAILED','CANCELLED'}
JOB_ID=re.compile(r'^[0-9a-f]{32}$')

def validate_request(data):
    if not isinstance(data,dict) or set(data)-{'prompt','max_duration_seconds','seed'}:raise ValueError('Only prompt, max_duration_seconds and seed are accepted; no file paths or command arguments.')
    prompt=data.get('prompt','')
    if not isinstance(prompt,str) or not 1<=len(prompt.strip())<=2000 or '\x00' in prompt:raise ValueError('Prompt must contain 1..2000 characters.')
    seconds=float(data.get('max_duration_seconds',3));seed=data.get('seed',42)
    if not math.isfinite(seconds) or not .05<=seconds<=10:raise ValueError('This audited backend supports duration caps 0.05..10 seconds.')
    if isinstance(seed,bool) or not isinstance(seed,int) or not 0<=seed<2**31:raise ValueError('Seed must be an integer in [0, 2^31).')
    return dict(prompt=prompt.strip(),max_duration_seconds=seconds,seed=seed)

class GenerationQueue:
    def __init__(self,config):
        self.config=config;self.jobs={};self.pending=collections.deque();self.lock=threading.RLock();self.wake=threading.Event();self.stopping=False
        self.worker=None;self.model_ready=False;self.events=queue.Queue();self.current=None;self.log=None;self.log_tail=collections.deque(maxlen=40)
        for path in config.data.glob('*/job.json'):
            try:
                job=json.loads(path.read_text(encoding='utf8'))
                if not JOB_ID.fullmatch(job['job_id']) or path.parent.name!=job['job_id']:continue
                if job['status'] not in FINAL:job.update(status='FAILED',stage='INTERRUPTED',error=dict(code='SERVER_RESTARTED',message='Previous server ended before completion; regenerate this segment.'));atomic_json(path,job)
                self.jobs[job['job_id']]=job
            except (OSError,ValueError,KeyError):continue
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def persist(self,job):atomic_json(self.config.data/job['job_id']/'job.json',job)
    def submit(self,data,kind='generate'):
        values=validate_request(data)
        with self.lock:
            if self.stopping:raise RuntimeError('Backend is stopping.')
            if sum(j['status'] not in FINAL for j in self.jobs.values())>=16:raise RuntimeError('Single-GPU queue is full (16).')
            job=dict(values,job_id=uuid.uuid4().hex,kind=kind,status='QUEUED',stage='WAITING_FOR_GPU',progress=None,created_at=time.time(),cancel_requested=False)
            folder=self.config.data/job['job_id'];folder.mkdir();self.jobs[job['job_id']]=job;self.pending.append(job['job_id']);self.persist(job);self.wake.set()
            return dict(job)
    def get(self,key):
        with self.lock:
            if not JOB_ID.fullmatch(key) or key not in self.jobs:raise KeyError('Unknown job ID.')
            value=dict(self.jobs[key]);value['queue_position']=list(self.pending).index(key)+1 if key in self.pending else 0
            return value
    def cancel(self,key):
        with self.lock:
            job=self.jobs[self.get(key)['job_id']]
            if job['status'] in FINAL:return dict(job)
            job.update(cancel_requested=True,cancel_requested_at=time.monotonic())
            (self.config.data/key/'cancel').touch()
            if job['status']=='QUEUED':
                self.pending.remove(key);job.update(status='CANCELLED',stage='CANCELLED_PENDING')
            else:job.update(status='CANCELLING',stage='COOPERATIVE_CANCELLATION')
            self.persist(job);return dict(job)
    def start_worker(self):
        if self.worker and self.worker.poll() is None:return
        self.events=queue.Queue();self.log=(self.config.data/'worker.log').open('a',encoding='utf8',buffering=1)
        self.worker=subprocess.Popen([str(self.config.python),'-I',str(Path(__file__).with_name('inference_worker.py')),str(self.config.config_path)],
            cwd=str(self.config.project),env=self.config.environment(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,encoding='utf8',errors='replace',bufsize=1,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        proc=self.worker;events=self.events;log=self.log
        def collect():
            for line in proc.stdout:
                log.write(line);self.log_tail.append(line.rstrip())
                if line.startswith('AMB_EVENT '):
                    try:events.put(json.loads(line[10:]))
                    except ValueError:pass
            events.put(dict(event='WORKER_EXIT',returncode=proc.poll()))
        threading.Thread(target=collect,daemon=True).start()
    def kill_worker(self):
        if self.worker:
            if self.worker.poll() is None:
                self.worker.terminate()
                try:self.worker.wait(timeout=8)
                except subprocess.TimeoutExpired:self.worker.kill();self.worker.wait(timeout=5)
            self.worker=None
            self.model_ready=False
    def run(self):
        while not self.stopping:
            self.wake.wait(.5);self.wake.clear()
            with self.lock:
                if not self.pending:continue
                key=self.pending.popleft();job=self.jobs[key];self.current=key;job.update(status='RUNNING',stage='STARTING_WORKER',started_at=time.time());self.persist(job)
            try:
                self.start_worker();self.worker.stdin.write(json.dumps(dict(job))+'\n');self.worker.stdin.flush();start=time.monotonic()
                gpu_samples=[];last_sample=0.
                while True:
                    if time.monotonic()-last_sample>1:
                        last_sample=time.monotonic()
                        try:
                            sample=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],timeout=2,text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                            gpu_samples.append(float(sample.strip().splitlines()[0]))
                        except (OSError,ValueError,subprocess.SubprocessError):pass
                    if job.get('cancel_requested') and time.monotonic()-job['cancel_requested_at']>8:
                        self.kill_worker();job.update(status='CANCELLED',stage='CANCELLED_WORKER_RESTART',cancellation_method='owned worker terminated after 8-second cooperative grace');break
                    if time.monotonic()-start>600:raise TimeoutError('Inference exceeded 600 seconds; owned worker will restart.')
                    try:event=self.events.get(timeout=.25)
                    except queue.Empty:
                        if self.worker.poll() is not None:raise RuntimeError('Inference worker exited unexpectedly; see log_tail.')
                        continue
                    kind=event['event']
                    if kind=='READY':continue
                    if kind=='WORKER_EXIT':raise RuntimeError('Inference worker exited: '+str(event.get('returncode')))
                    if event.get('job_id')!=key:continue
                    with self.lock:
                        if kind=='PROGRESS':
                            if not job.get('cancel_requested'):job.update({k:v for k,v in event.items() if k not in ['event','job_id']})
                        elif kind=='DONE':
                            self.model_ready=True
                            event['metrics'].update(whole_gpu_peak_MiB_sampled=max(gpu_samples) if gpu_samples else None,
                                whole_gpu_baseline_MiB=gpu_samples[0] if gpu_samples else None,whole_gpu_sample_count=len(gpu_samples),
                                gpu_measurement_note='Parent samples whole card at ~1s; includes desktop/other apps, may miss peaks. Torch allocator metrics exclude native/driver allocations.')
                            if job.get('cancel_requested'):job.update(status='CANCELLED',stage='CANCELLED_BEFORE_PUBLICATION')
                            else:job.update(status='DONE',stage='COMPLETE',progress=1.,duration=event['duration'],metrics=event['metrics'],elapsed_seconds=event['elapsed_seconds'])
                            break
                        elif kind=='CANCELLED':job.update(status='CANCELLED',stage='CANCELLED_COOPERATIVE',message=event['message']);break
                        elif kind=='FAILED':
                            job.update(status='FAILED',stage='ERROR',error=event['error'])
                            if event.get('restart_worker'):self.kill_worker();job['worker_restarted']=True
                            break
                        self.persist(job)
            except Exception as exc:
                self.kill_worker();job.update(status='FAILED',stage='WORKER_ERROR',error=dict(code=type(exc).__name__,message=str(exc),log_tail=list(self.log_tail)))
            finally:
                with self.lock:
                    job['finished_at']=time.time();job['log_tail']=list(self.log_tail);self.persist(job);self.current=None
                    if self.pending:self.wake.set()
        self.kill_worker()
    def close(self):
        with self.lock:
            for key,job in self.jobs.items():
                if job['status'] not in FINAL:self.cancel(key)
        deadline=time.monotonic()+9
        while self.current and time.monotonic()<deadline:time.sleep(.1)
        self.stopping=True;self.wake.set();self.thread.join(timeout=15);self.kill_worker()
