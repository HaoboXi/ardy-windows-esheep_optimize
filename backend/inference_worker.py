"""Persistent child. JSON events on stdout; parent owns all paths and GPU queue."""
import json,os,sys,threading,time,traceback,types,subprocess,faulthandler
from pathlib import Path
if not __package__:
    package=types.ModuleType('amb_backend');package.__path__=[str(Path(__file__).resolve().parent)];sys.modules['amb_backend']=package;__package__='amb_backend'
from .runtime_config import RuntimeConfig,ProcessLock
from .model_manager import ModelManager,Cancelled
from .motion_export import save_npz,export_trimmed

def event(value):print('AMB_EVENT '+json.dumps(value,ensure_ascii=True,allow_nan=False),flush=True)
def main():
    sys.stdout.reconfigure(encoding='utf-8',line_buffering=True);sys.stderr.reconfigure(encoding='utf-8',line_buffering=True)
    faulthandler.enable()
    config=RuntimeConfig(sys.argv[1]);os.environ.update(config.environment());os.chdir(config.project);sys.path.insert(0,str(config.project))
    # Import native BLAS before Python pipe-reader threads exist. On Windows a
    # concurrent subprocess/reader thread can wait on the DLL loader lock.
    import scipy.linalg
    commands=__import__('queue').Queue();lost_parent=threading.Event()
    def reader():
        for line in sys.stdin:
            commands.put(json.loads(line))
        lost_parent.set()
        # If native code is stuck, release this owned worker after parent loss.
        time.sleep(8);os._exit(91)
    threading.Thread(target=reader,daemon=True).start()
    with ProcessLock(config.lock_dir/'cuda0.model.lock'),ProcessLock(config.lock_dir/(config.key+'.model.lock')):
        manager=ModelManager(config);event(dict(event='READY',pid=os.getpid()))
        while not lost_parent.is_set():
            try:job=commands.get(timeout=.5)
            except __import__('queue').Empty:continue
            folder=config.data/job['job_id'];cancel=folder/'cancel';started=time.perf_counter()
            def check():
                if cancel.exists() or lost_parent.is_set():raise Cancelled('Cancellation requested; incomplete result is not published.')
            def notify(**data):event(dict(event='PROGRESS',job_id=job['job_id'],**data))
            try:
                check();motion,metrics=manager.generate(job,notify,check);notify(stage='EXPORT',progress=None)
                raw=folder/'raw.npz';target=folder/'motion.npz';save_npz(raw,motion,job['prompt']);check()
                report=export_trimmed(raw,target,job['max_duration_seconds'],job['prompt']);check()
                event(dict(event='DONE',job_id=job['job_id'],duration=report,metrics=metrics,elapsed_seconds=time.perf_counter()-started))
            except Cancelled as exc:event(dict(event='CANCELLED',job_id=job['job_id'],message=str(exc)))
            except Exception as exc:
                oom='out of memory' in str(exc).lower()
                event(dict(event='FAILED',job_id=job['job_id'],error=dict(code='CUDA_OOM' if oom else type(exc).__name__,message=str(exc),traceback=traceback.format_exc()),restart_worker=oom))
if __name__=='__main__':main()
