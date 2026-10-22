"""Pure NumPy Core interchange. No backend imports, pickle, or model execution."""
import json
from pathlib import Path
import zipfile
import numpy as np

SKELETON = json.loads(Path(__file__).with_name('skeleton_core.json').read_text(encoding='utf-8'))
NAMES = SKELETON['joint_names']
PARENTS = SKELETON['parents']
REST = np.array(SKELETON['rest_joints_m'], dtype=np.float64)
# Right-handed: Core +X left, +Y up, +Z forward -> Blender +X left, +Z up, -Y forward.
C = np.array([[1., 0., 0.], [0., 0., -1.], [0., 1., 0.]])
MAX_BYTES = 512 * 1024 * 1024
MAX_FRAMES = 10000


class MotionError(ValueError):
    pass


def fk(local, root):
    g = np.empty_like(local, dtype=np.float64)
    p = np.empty(local.shape[:2] + (3,), dtype=np.float64)
    for j, parent in enumerate(PARENTS):
        if parent < 0:
            g[:, j] = local[:, j]
            p[:, j] = root
        else:
            g[:, j] = g[:, parent] @ local[:, j]
            p[:, j] = p[:, parent] + np.einsum('tij,j->ti', g[:, parent], REST[j]-REST[parent])
    return g, p


def load_motion(path):
    path = Path(path)
    try:
        if path.suffix.lower() != '.npz' or not 0 < path.stat().st_size <= MAX_BYTES:
            raise MotionError('NPZ file must be nonempty and at most 512 MiB.')
        with zipfile.ZipFile(path) as z:
            members = z.infolist()
            if len(members) > 32 or len({m.filename for m in members}) != len(members):
                raise MotionError('NPZ has too many arrays or duplicate ZIP members.')
            if sum(m.file_size for m in members) > MAX_BYTES:
                raise MotionError('Uncompressed NPZ exceeds 512 MiB.')
            for m in members:
                if '/' in m.filename or '\\' in m.filename or not m.filename.endswith('.npy'):
                    raise MotionError('Unexpected archive member: ' + m.filename)
                with z.open(m) as f:
                    version = np.lib.format.read_magic(f)
                    if version == (1,0):
                        shape, _, dtype = np.lib.format.read_array_header_1_0(f, max_header_size=16384)
                    elif version == (2,0):
                        shape, _, dtype = np.lib.format.read_array_header_2_0(f, max_header_size=16384)
                    else:
                        raise MotionError('Unsupported NPY header version; re-export with standard NumPy savez.')
                    if dtype.hasobject or dtype.fields or dtype.kind not in 'biufSU':
                        raise MotionError('Unsafe/unsupported dtype in ' + m.filename)
                    count = 1
                    for dim in shape:
                        count *= dim
                    if count * dtype.itemsize > MAX_BYTES or count * dtype.itemsize > m.file_size:
                        raise MotionError('Invalid or oversized NPY header: ' + m.filename)
        with np.load(path, allow_pickle=False, max_header_size=16384) as z:
            required = ['posed_joints', 'local_rot_mats', 'global_rot_mats', 'root_positions', 'fps', 'foot_contacts']
            missing = set(required) - set(z.files)
            if missing:
                raise MotionError('Missing arrays: ' + ', '.join(sorted(missing)))
            d = {k: z[k] for k in required}
        t = len(d['root_positions'])
        if not 1 <= t <= MAX_FRAMES:
            raise MotionError('Expected 1..10000 frames of one Core27 sample (no batch dimension).')
        shapes = dict(posed_joints=(t,27,3), local_rot_mats=(t,27,3,3), global_rot_mats=(t,27,3,3),
                      root_positions=(t,3), foot_contacts=(t,4))
        for k, a in d.items():
            if a.dtype.kind not in 'biuf' or (k not in ('fps','foot_contacts') and a.dtype.kind != 'f'):
                raise MotionError(k + ': expected real numeric floating-point motion data.')
            if not np.isfinite(a).all():
                raise MotionError(k + ': contains NaN/Inf.')
            if k in shapes and a.shape != shapes[k]:
                raise MotionError(f'{k}: expected {shapes[k]}, got {a.shape}.')
        if d['fps'].shape not in ((), (1,)):
            raise MotionError('fps must be a scalar.')
        fps = float(d['fps'].reshape(-1)[0])
        if not 1 <= fps <= 240:
            raise MotionError('fps must be finite and within 1..240.')
        if np.min(d['foot_contacts']) < 0 or np.max(d['foot_contacts']) > 1:
            raise MotionError('foot_contacts must be Boolean or probabilities in [0,1].')
        for k in ('local_rot_mats','global_rot_mats'):
            a = d[k].astype(np.float64)
            if np.max(abs(a.swapaxes(-1,-2) @ a - np.eye(3))) > 2e-3 or np.max(abs(np.linalg.det(a)-1)) > 2e-3:
                raise MotionError(k + ': not proper orthonormal rotation matrices.')
        g, p = fk(d['local_rot_mats'], d['root_positions'])
        ge = float(np.max(abs(g-d['global_rot_mats'])))
        pe = float(np.max(abs(p-d['posed_joints'])))
        if ge > 3e-3 or pe > 3e-3:
            raise MotionError(f'Core27 FK mismatch (rotation {ge:.6g}, position {pe:.6g} m). Check skeleton/version or position-based export.')
        d.update(fps=fps, frames=t, global_rot_mats=g, fk_position_error_m=pe,
                 fk_rotation_error=ge, path=str(path.resolve()), file_bytes=path.stat().st_size)
        return d
    except MotionError:
        raise
    except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile, OverflowError, TypeError) as e:
        raise MotionError('Cannot read Core NPZ: ' + str(e)) from e
