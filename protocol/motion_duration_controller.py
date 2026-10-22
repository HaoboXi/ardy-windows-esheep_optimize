"""Pure NumPy duration budgets; shared with the independent service via fixed-file import."""
from decimal import Decimal,ROUND_FLOOR
import math,numpy as np

def frame_budget(seconds,fps):
    seconds=float(seconds);fps=float(fps)
    if not math.isfinite(seconds) or not .0<seconds<=600 or not math.isfinite(fps) or not 1<=fps<=240:raise ValueError('Invalid duration / FPS.')
    n=int((Decimal(str(seconds))*Decimal(str(fps))+Decimal('0.000000001')).to_integral_value(rounding=ROUND_FLOOR))
    if n<1:raise ValueError('Duration is shorter than one sample at the actual FPS.')
    return n

def periodicity_diagnostic(motion):
    """Report approximate pose/root-relative recurrence; never delete legitimate gait cycles."""
    r=np.asarray(motion['local_rot_mats']);p=np.asarray(motion['root_positions']);fps=float(motion['fps']);n=len(p)
    candidates=[]
    for lag in range(max(2,int(fps*.4)),min(n//2,int(fps*3))+1):
        pose=float(np.mean((r[lag:]-r[:-lag])**2))
        displacement=p[lag:]-p[:-lag]
        root_repeat=float(np.mean((displacement-displacement.mean(0))**2))
        candidates.append((pose+root_repeat,lag,pose,root_repeat))
    best=min(candidates) if candidates else None
    return dict(policy='DIAGNOSTIC_ONLY_NO_TILING_NO_CYCLE_DELETION',candidate_lag_frames=best[1] if best else None,
        pose_matrix_mse=best[2] if best else None,root_relative_mse_m2=best[3] if best else None,
        semantic_end_detected=False,note='Walking is legitimately periodic. No semantic completion is inferred from recurrence or stillness.')

def trim_motion(motion,maximum_seconds):
    budget=frame_budget(maximum_seconds,motion['fps']);original=int(motion['frames']);n=min(original,budget)
    keys=['local_rot_mats','global_rot_mats','root_positions','posed_joints','foot_contacts']
    result={k:np.array(motion[k][:n],copy=True) for k in keys};result.update(fps=float(motion['fps']),frames=n,path=motion.get('path',''))
    speed=float(np.linalg.norm(motion['root_positions'][n-1]-motion['root_positions'][n-2])*motion['fps']) if n>1 else 0.
    report=dict(schema='ardy.duration.v1',requested_max_seconds=float(maximum_seconds),fps=result['fps'],frame_budget=budget,
        generated_frames=original,trimmed_frames=n,generated_duration_seconds=original/result['fps'],actual_duration_seconds=n/result['fps'],
        sample_span_seconds=(n-1)/result['fps'],last_sample_time_seconds=(n-1)/result['fps'],
        reason='MAX_DURATION_LIMIT' if original>n else 'MODEL_LENGTH_WITHIN_BUDGET',natural_completion_claimed=False,
        tail_root_speed_m_s=speed,tail_requires_transition=bool(speed>.15),
        final_root_position=result['root_positions'][-1].tolist(),final_local_rot_mats=result['local_rot_mats'][-1].tolist(),
        periodicity=periodicity_diagnostic(result))
    return result,report
