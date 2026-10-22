"""JSON-lines CPU process. Never imported by Blender or the NF4 worker."""
import json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from translation_text import validate_english,semantic_warnings
from translation_engine import translate

def main():
    model=Path(sys.argv[1]);translator=None;sp=None
    for line in sys.stdin:
        try:
            text=json.loads(line)['text'];t=time.perf_counter();load=0.
            if translator is None:
                import ctranslate2,sentencepiece
                sp=sentencepiece.SentencePieceProcessor(model_file=str(model/'sentencepiece.model'))
                translator=ctranslate2.Translator(str(model/'model'),device='cpu',compute_type='int8',inter_threads=1,intra_threads=4)
                load=(time.perf_counter()-t)*1000
            result=translate(text,sp,translator)
            result.update(model_load_ms=load,worker_ms=(time.perf_counter()-t)*1000,device='cpu')
        except Exception as exc:result=dict(error=type(exc).__name__+': '+str(exc))
        print(json.dumps(result,ensure_ascii=True),flush=True)
if __name__=='__main__':main()
