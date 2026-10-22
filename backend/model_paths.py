"""Single local model path policy. No network, Torch, or home-folder overrides."""
import json,os
from pathlib import Path

NF4_REPO='Esheepbo/Esheep-ardy-llm2vec_NF4'
NF4_FOLDER='Esheep-ardy-llm2vec_NF4'
CORE_FOLDER='ARDY-Core-RP-20FPS-Horizon40'

class ModelPathResolver:
    def __init__(self,project_root,runtime_config=None,nf4_directory=None,core_directory=None):
        self.project=Path(project_root).resolve();self.settings={}
        configured=runtime_config or os.environ.get('ARDY_RUNTIME_CONFIG')
        self.config_path=Path(configured).resolve() if configured else self.project/'runtime_config.json'
        if self.config_path.is_file():
            if self.config_path.stat().st_size>65536:raise ValueError('Runtime model configuration exceeds 64 KiB.')
            self.settings=json.loads(self.config_path.read_text(encoding='utf8'))
            if self.settings.get('schema')!='ardy.runtime.v1':raise ValueError('Unsupported runtime model configuration.')
        models=self.settings.get('models',{})
        self.nf4_model=self.choose(models.get('nf4') or nf4_directory,self.project/'models'/NF4_FOLDER,self.project/'models/KIMODO-Meta3_llm2vec_NF4')
        self.core_model=self.choose(models.get('core') or core_directory,self.project/'checkpoints'/CORE_FOLDER)
    def choose(self,explicit,default,legacy=None):
        if explicit:
            p=Path(explicit)
            if not p.is_absolute():p=self.config_path.parent/p
            return p.resolve()
        if default.is_dir() or legacy is None:return default.resolve()
        return legacy.resolve() if legacy.is_dir() else default.resolve()
    def validate(self):
        for base,names in [(self.core_model,['config.yaml','denoiser.safetensors','tokenizer.safetensors','stats/motion/mean.npy','stats/motion/std.npy']),
            (self.nf4_model,['config.json','tokenizer.json','tokenizer_config.json','model.safetensors'])]:
            for name in names:
                p=base/name
                if not p.is_file() or p.stat().st_size==0:raise FileNotFoundError('Required local model file missing: '+str(p)+'. Verify/Repair the installation or select existing model files; inference never downloads weights.')
        q=json.loads((self.nf4_model/'config.json').read_text(encoding='utf8')).get('quantization_config',{})
        if not q.get('load_in_4bit') or q.get('bnb_4bit_quant_type')!='nf4' or not q.get('bnb_4bit_use_double_quant'):
            raise ValueError('Expected NF4 with double quantization; precision fallback is prohibited.')
        return self
