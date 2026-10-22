"""Authenticated loopback-only HTTP service; stdlib, one queued GPU child."""
import argparse,hmac,json,os,secrets,sys,threading,time,types,urllib.parse
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
if not __package__:
    package=types.ModuleType('amb_backend');package.__path__=[str(Path(__file__).resolve().parent)];sys.modules['amb_backend']=package;__package__='amb_backend'
from .runtime_config import RuntimeConfig,ProcessLock,atomic_json,capabilities
from .generation_queue import GenerationQueue
from .translation_service import TranslationService

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);args=p.parse_args();config=RuntimeConfig(args.config)
    token=secrets.token_urlsafe(32);session_id=secrets.token_hex(16);started=time.perf_counter();last_request=[time.monotonic()]
    with ProcessLock(config.lock_dir/(config.key+'.server.lock')):
        jobs=GenerationQueue(config)
        if config.runtime_path.is_file():os.environ['ARDY_RUNTIME_CONFIG']=str(config.runtime_path)
        translator=TranslationService(config.project,config.session_dir/'translation_cache')
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass  # Do not log authentication credentials.
            def reply(self,status,value):
                data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
            def handle_request(self,post=False):
                try:
                    if self.headers.get('Host')!=f'127.0.0.1:{config.port}' or self.headers.get('Origin'):
                        self.reply(403,dict(error='Local native clients only; Origin/Host rejected.'));return
                    if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):
                        self.reply(401,dict(error='Missing or invalid session credential.'));return
                    last_request[0]=time.monotonic();path=urllib.parse.urlsplit(self.path)
                    if path.query:raise ValueError('Query parameters are not supported.')
                    route=path.path;body={}
                    if post:
                        size=int(self.headers.get('Content-Length',0))
                        if not 0<=size<=16384:raise ValueError('Request body exceeds 16 KiB.')
                        body=json.loads(self.rfile.read(size)) if size else {}
                    if route=='/health' and not post:
                        self.reply(200,dict(schema='ardy.backend.health.v1',bridge_version='0.6.0',translation=translator.status(),status='BUSY' if jobs.current else 'READY',session_id=session_id,pid=os.getpid(),
                            worker_pid=jobs.worker.pid if jobs.worker and jobs.worker.poll() is None else None,active_job=jobs.current,pending=len(jobs.pending),
                            startup_seconds=startup,conda_python=str(config.python),project_root=str(config.project),model_loaded=jobs.model_ready,idle_shutdown_seconds=config.idle_seconds));return
                    if route=='/capabilities' and not post:self.reply(200,capabilities());return
                    if route=='/translation/status' and not post:self.reply(200,translator.status());return
                    if route=='/translate' and post:self.reply(200,translator.translate(body));return
                    if route=='/generate' and post:self.reply(202,jobs.submit(body));return
                    if route=='/diagnostics/history-probe' and post:
                        if body:raise ValueError('History probe uses a fixed diagnostic prompt and previous in-memory model features; no paths accepted.')
                        self.reply(202,jobs.submit(dict(prompt='The person gradually stops walking and stands still.',max_duration_seconds=1.,seed=4243),kind='history_probe'));return
                    if route=='/shutdown' and post:
                        self.reply(200,dict(status='STOPPING'));threading.Thread(target=http.shutdown,daemon=True).start();return
                    parts=route.strip('/').split('/')
                    if len(parts) in [2,3] and parts[0]=='jobs':
                        job=jobs.get(parts[1])
                        if len(parts)==2 and not post:self.reply(200,job);return
                        if parts[2:] == ['cancel'] and post:self.reply(200,jobs.cancel(parts[1]));return
                        if parts[2:]==['result'] and not post:
                            if job['status']!='DONE':self.reply(409,dict(error='Result is available only for a completed job.',status=job['status']));return
                            file=(config.data/parts[1]/'motion.npz').resolve()
                            if file.parent!=(config.data/parts[1]).resolve() or not file.is_relative_to(config.data):raise ValueError('Result escaped the owned job directory.')
                            data=file.read_bytes();self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(len(data)));self.send_header('X-Content-SHA256',job['duration']['sha256']);self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data);return
                    self.reply(404,dict(error='Unknown endpoint.'))
                except KeyError as exc:self.reply(404,dict(error=str(exc)))
                except (ValueError,TypeError,OverflowError) as exc:self.reply(400,dict(error=str(exc)))
                except (BrokenPipeError,ConnectionResetError):pass
                except Exception as exc:self.reply(500,dict(error=type(exc).__name__,message=str(exc)))
            def do_GET(self):self.handle_request()
            def do_POST(self):self.handle_request(True)
        try:
            http=ThreadingHTTPServer(('127.0.0.1',config.port),Handler);http.daemon_threads=True;startup=time.perf_counter()-started
            atomic_json(config.session_path,dict(schema='ardy.backend.session.v1',host='127.0.0.1',port=config.port,token=token,session_id=session_id,pid=os.getpid(),created_at=time.time()))
            print('ARDY backend ready on 127.0.0.1:'+str(config.port),flush=True)
            def idle():
                while True:
                    time.sleep(2)
                    if not jobs.current and not jobs.pending and time.monotonic()-last_request[0]>config.idle_seconds:http.shutdown();return
            threading.Thread(target=idle,daemon=True).start();http.serve_forever(poll_interval=.25)
        finally:
            translator.close()
            jobs.close()
            if 'http' in locals():http.server_close()
            try:
                if json.loads(config.session_path.read_text(encoding='utf8')).get('session_id')==session_id:config.session_path.unlink()
            except (FileNotFoundError,ValueError):pass
if __name__=='__main__':main()
