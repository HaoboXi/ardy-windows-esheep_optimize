"""Persistent, unchanged Core/NF4 loading and generation inside Conda only."""
import math,time
import numpy as np

class Cancelled(Exception):pass
class InsufficientVRAM(RuntimeError):pass

def check_capacity(torch):
    free,total=torch.cuda.mem_get_info()
    reusable=max(0,torch.cuda.memory_reserved()-torch.cuda.memory_allocated())
    # Audited ~5.2GiB allocator peak plus headroom. Reusable cache belongs to
    # this worker, not another application. This is a guard, not an OOM proof.
    required=int(5.75*2**30)
    if free+reusable<required:raise InsufficientVRAM('GPU_BUSY_CAPACITY: only %.0f MiB free/reusable; verified NF4 loading needs an estimated %.0f MiB. Close competing GPU jobs and retry. No precision fallback is used.'%((free+reusable)/2**20,required/2**20))
    return dict(free_MiB=free/2**20,reusable_worker_cache_MiB=reusable/2**20,estimated_required_MiB=required/2**20,total_MiB=total/2**20)

class ModelManager:
    def __init__(self,config):self.config=config;self.model=None;self.load_seconds=0.;self.last_features=None;self.calls=0
    def load(self,notify,check):
        if self.model is not None:return
        check();notify(stage='LOADING_MODEL',progress=None)
        started=time.perf_counter()
        import torch
        if not torch.cuda.is_available():raise RuntimeError('CUDA GPU is unavailable in the configured Conda environment; CPU fallback is disabled.')
        from ardy.model.memory_manager import manager
        from ardy.model import load_model
        from .runtime_config import MODEL
        manager.offload_enabled=True
        self.model=load_model(MODEL,device='cuda:0',checkpoints_dir=str(self.config.paths.core_model.parent),text_encoder_mode='local')
        if self.model.motion_rep.fps!=20 or self.model.num_frames_per_token!=4 or self.model.diffusion.num_base_steps!=10:raise RuntimeError('Local Core capability differs from the audited 20FPS / token4 / steps10 configuration.')
        self.load_seconds=time.perf_counter()-started;check()
    def generate(self,job,notify,check):
        import torch
        from ardy.motion_rep.tools import length_to_mask
        from ardy.tools import seed_everything,to_numpy
        from ardy.postprocess import post_process_motion
        if not torch.cuda.is_available():raise RuntimeError('CUDA GPU is unavailable in the configured Conda environment; CPU fallback is disabled.')
        notify(stage='GPU_CAPACITY_CHECK',progress=None);capacity=check_capacity(torch)
        torch.cuda.reset_peak_memory_stats();cold=self.model is None;self.load(notify,check);m=self.model
        from .motion_export import duration
        from .runtime_config import MODEL
        from ardy.model.memory_manager import manager
        from ardy.model.loading import MODEL_INIT_LOCK
        requested=duration.frame_budget(job['max_duration_seconds'],m.motion_rep.fps)
        n=max(4,int(math.ceil(requested/4)*4));history=None;probe=None
        if job.get('kind')=='history_probe':
            if self.last_features is None:raise ValueError('Generate a real motion before testing the normalized-history interface.')
            history=self.last_features[:,-8:].to(m.device);n+=history.shape[1]
        seed_everything(job['seed']);lengths=torch.tensor([n],device=m.device);pad=length_to_mask(lengths)
        h=0 if history is None else history.shape[1];total=int(math.ceil((n-h)/m.gen_horizon_len))*10;done=0;encoding_seconds=0.
        def progress(values):
            nonlocal done
            for value in values:
                check();notify(stage='DIFFUSION',completed_steps=done,total_steps=total,progress=done/total)
                yield value
                done+=1
            notify(stage='DIFFUSION',completed_steps=done,total_steps=total,progress=done/total)
        started=time.perf_counter();notify(stage='TEXT_ENCODING',progress=None)
        # Same public API, CFG, precision, offload and postprocess as generate.py.
        with torch.no_grad():
            manager.touch_and_move(MODEL,m.device)
            t=time.perf_counter();text_feat,text_pad=m._encode_text([job['prompt']]);encoding_seconds=time.perf_counter()-t;check()
            kwargs=dict(num_denoising_steps=10,pad_mask=pad,cfg_weight=(2.,2.),text_feat=text_feat,text_pad_mask=text_pad,
                progress_bar=progress,first_heading_angle=torch.zeros(1,device=m.device),crop_history_length=160,motion_mask=None,observed_motion=None)
            if history is not None:
                kwargs.update(init_history_sequence=history,first_heading_angle=None,crop_history_length=None)
                consumed=[];original=m._encode_init_history
                def track(*args,**kw):consumed.append(list(args[0].shape));return original(*args,**kw)
                m._encode_init_history=track
            try:features=m([job['prompt']],n,**kwargs)
            finally:
                if history is not None:m._encode_init_history=original
            check();output=m.motion_rep.inverse(features,is_normalized=True)
            if history is not None:
                expected=m.motion_rep.inverse(history,is_normalized=True)
                root_error=torch.linalg.vector_norm(output['root_positions'][:,:h]-expected['root_positions'],dim=-1).max().item()
                r0=output['global_rot_mats'][:,:h];r1=expected['global_rot_mats'];cos=((r0.transpose(-1,-2)@r1).diagonal(dim1=-2,dim2=-1).sum(-1)-1)/2
                angle=torch.rad2deg(torch.acos(cos.clamp(-1,1))).max().item()
                new_root_gap=torch.linalg.vector_norm(output['root_positions'][:,h]-expected['root_positions'][:,-1],dim=-1).max().item()
                probe=dict(source_interface_consumed=bool(consumed),consumed_shapes=consumed,normalized_history_frames=h,
                    reconstructed_history_root_error_m=root_error,reconstructed_history_global_rotation_error_deg=angle,
                    first_new_frame_root_distance_to_previous_tail_m=new_root_gap,
                    arbitrary_PMX_single_tail_pose_supported=False,
                    result='EXPERIMENTAL_NORMALIZED_HISTORY_CONSUMED_NOT_A_PMX_TAIL_CONSTRAINT',production_mode='POST_PROCESS_STITCHED')
                output={k:v[:,h:] if hasattr(v,'shape') and v.ndim>=2 and v.shape[1]==n else v for k,v in output.items()}
                features=features[:,h:];n-=h
            self.last_features=features.detach().cpu()
            notify(stage='POSTPROCESS',progress=None);check()
            corrected=post_process_motion(output['local_rot_mats'],output['root_positions'],output['foot_contacts'],m.skeleton,constraint_lst=None)
            output.update(corrected)
        check();torch.cuda.synchronize();elapsed=time.perf_counter()-started;self.calls+=1
        # Audit actual quantized layers after the lazy NF4 encoder load.
        from bitsandbytes.nn import Linear4bit
        layers=[v for v in m.text_encoder.model.model.modules() if isinstance(v,Linear4bit)]
        if not layers or any(v.weight.quant_state is None or v.weight.quant_state.quant_type!='nf4' for v in layers):raise RuntimeError('Actual NF4 layer audit failed; precision must remain unchanged.')
        metrics=dict(cold_model_load=cold,core_model_load_seconds=self.load_seconds if cold else 0.,text_encoding_seconds=encoding_seconds,
            inference_postprocess_seconds=elapsed,first_model_ready_seconds=self.load_seconds+encoding_seconds if cold else None,
            model_reused=not cold,generation_count_in_worker=self.calls,actual_nf4_linear_layers=len(layers),
            gpu=torch.cuda.get_device_name(),gpu_total_MiB=torch.cuda.get_device_properties(0).total_memory/2**20,
            torch_peak_allocated_MiB=torch.cuda.max_memory_allocated()/2**20,torch_peak_reserved_MiB=torch.cuda.max_memory_reserved()/2**20,
            torch=str(torch.__version__),cuda_runtime=str(torch.version.cuda),model=MODEL,offload=True,double_quantization=True,
            seed=job['seed'],num_frames=n,fps=float(m.motion_rep.fps),diffusion_steps=10,history_frames=160 if history is None else None,
            conditioning_mode='POST_PROCESS_STITCHED',conditioning_probe=probe,gpu_capacity_preflight=capacity)
        arrays=to_numpy(output);motion={k:arrays[k][0] for k in ['local_rot_mats','global_rot_mats','root_positions','posed_joints','foot_contacts']}
        motion['fps']=float(m.motion_rep.fps)
        return motion,metrics
