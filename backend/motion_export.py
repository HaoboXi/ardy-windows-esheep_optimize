"""Reuse the exact strict NPZ validator without importing bpy or the Blender addon package."""
import hashlib,importlib.util,os
from pathlib import Path
import numpy as np

def addon_dir():
    here=Path(__file__).resolve().parent
    return here.parent if (here.parent/'motion.py').is_file() else here.parent/'protocol' if (here.parent/'protocol/motion.py').is_file() else here.parent/'ardy_motion_bridge'

def fixed_module(name):
    path=addon_dir()/(name+'.py');spec=importlib.util.spec_from_file_location('amb_'+name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

validator=fixed_module('motion');duration=fixed_module('motion_duration_controller')

def sha256(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save_npz(path,motion,text):
    path=Path(path)
    if path.exists():raise FileExistsError('Immutable result already exists: '+str(path))
    temp=path.with_suffix('.partial.npz')
    arrays={k:np.asarray(motion[k]) for k in ['local_rot_mats','global_rot_mats','posed_joints','root_positions','foot_contacts']}
    np.savez(temp,**arrays,fps=np.asarray(motion['fps']),text=np.asarray(text))
    validator.load_motion(temp);os.replace(temp,path)

def export_trimmed(raw_path,target_path,seconds,prompt):
    raw=validator.load_motion(raw_path);motion,report=duration.trim_motion(raw,seconds);save_npz(target_path,motion,prompt)
    report.update(raw_sha256=sha256(raw_path),sha256=sha256(target_path),raw_npz_path=str(raw_path),generated_npz_path=str(target_path))
    return report
