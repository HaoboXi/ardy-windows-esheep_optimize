"""Export one ARDY Core NPZ sample as a Blender-importable BVH.

BVH stores centimetres, Y-up, +Z-forward and intrinsic ZXY rotation channels.
The companion JSON preserves the original Core hierarchy/rest pose in metres.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from ardy.skeleton import CoreSkeleton27


def export_core_bvh(input_path: Path, output_path: Path) -> dict:
    skeleton = CoreSkeleton27()
    names = skeleton.bone_order_names
    parents = skeleton.joint_parents.numpy()
    rest = skeleton.neutral_joints.numpy().astype(np.float64)
    with np.load(input_path, allow_pickle=False) as data:
        rotations = np.asarray(data['local_rot_mats'], dtype=np.float64)
        root = np.asarray(data['root_positions'], dtype=np.float64)
        fps = float(np.asarray(data['fps']).item())
    frames = rotations.shape[0]
    if rotations.shape != (frames, 27, 3, 3) or root.shape != (frames, 3) or frames < 1:
        raise ValueError('Expected one Core sample: rotations [T,27,3,3], root [T,3].')
    if not np.isfinite(fps) or fps <= 0 or not np.isfinite(rotations).all() or not np.isfinite(root).all():
        raise ValueError('FPS must be positive and all motion values must be finite.')
    orthogonal_error = np.max(np.abs(rotations.swapaxes(-1, -2) @ rotations - np.eye(3)))
    if orthogonal_error > 1e-3 or np.max(np.abs(np.linalg.det(rotations) - 1)) > 1e-3:
        raise ValueError('local_rot_mats contains invalid rotation matrices.')

    # BVH channels follow hierarchy traversal, which may differ from array order.
    children = [[i for i, parent in enumerate(parents) if parent == j] for j in range(27)]
    order = []
    hierarchy = ['HIERARCHY']

    def add_joint(joint, depth):
        order.append(joint)
        indent = '  ' * depth
        parent = parents[joint]
        offset = np.zeros(3) if parent < 0 else rest[joint] - rest[parent]
        kind = 'ROOT' if parent < 0 else 'JOINT'
        hierarchy.extend([f'{indent}{kind} {names[joint]}', f'{indent}{{'])
        hierarchy.append(f'{indent}  OFFSET ' + ' '.join(f'{value * 100:.9f}' for value in offset))
        channels = '6 Xposition Yposition Zposition' if parent < 0 else '3'
        hierarchy.append(f'{indent}  CHANNELS {channels} Zrotation Xrotation Yrotation')
        for child in children[joint]:
            add_joint(child, depth + 1)
        if not children[joint]:
            # End Sites only give terminal bones a visible tail; they add no joints/channels.
            tail = offset * 0.25
            if np.linalg.norm(tail) < 1e-6:
                tail = np.array([0.0, 0.01, 0.0])
            hierarchy.extend([
                f'{indent}  End Site', f'{indent}  {{',
                f'{indent}    OFFSET ' + ' '.join(f'{value * 100:.9f}' for value in tail),
                f'{indent}  }}',
            ])
        hierarchy.append(f'{indent}}}')

    add_joint(skeleton.root_idx, 0)
    euler = Rotation.from_matrix(rotations.reshape(-1, 3, 3)).as_euler('ZXY')
    euler = np.rad2deg(np.unwrap(euler.reshape(frames, 27, 3), axis=0))
    channels = np.concatenate([root * 100, euler[:, order].reshape(frames, -1)], axis=1)
    metadata = {
        'schema': 'ardy.core_skeleton.v1', 'skeleton': 'cskel27',
        'joint_names': names, 'parents': parents.tolist(),
        'rest_joints_m': rest.tolist(), 'up_axis': '+Y', 'forward_axis': '+Z',
        'source_position_unit': 'metre', 'fps': fps, 'frames': frames,
        'bvh_position_unit': 'centimetre', 'bvh_rotation_order': 'ZXY',
        'blender_import': {
            'target': 'ARMATURE', 'global_scale': 0.01, 'frame_start': 1,
            'rotate_mode': 'NATIVE', 'axis_forward': 'Z', 'axis_up': 'Y',
            'use_fps_scale': False, 'update_scene_fps': True, 'update_scene_duration': True,
        },
    }
    metadata_path = output_path.with_suffix('.skeleton.json')
    for path in [output_path, metadata_path]:
        if path.exists():
            raise FileExistsError(f'Refusing to overwrite {path}')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('x', encoding='utf-8') as file:
        file.write('\n'.join(hierarchy) + '\nMOTION\n')
        file.write(f'Frames: {frames}\nFrame Time: {1 / fps:.12f}\n')
        np.savetxt(file, channels, fmt='%.9f')
    metadata_path.write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='Single-sample Core .npz from scripts/generate.py')
    parser.add_argument('--output', type=Path, help='BVH path; defaults to the input path with .bvh suffix')
    args = parser.parse_args()
    output = args.output or args.input.with_suffix('.bvh')
    metadata = export_core_bvh(args.input, output)
    print(f'Saved {output}: {metadata["frames"]} frames, {metadata["fps"]:g} FPS, 27 joints')
    print(f'Skeleton metadata: {output.with_suffix(".skeleton.json")}')
    print('Blender: Armature, Scale 0.01, Forward Z, Up Y, Rotation Native, Update Scene FPS.')


if __name__ == '__main__':
    main()
