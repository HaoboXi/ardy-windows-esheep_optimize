# ARDY Windows / NF4 Motion Bridge backend 0.6.0

Windows deployment of the existing ARDY Core27 inference stack for ARDY Motion
Bridge and Blender PMX/MMD characters. This is a community Windows/NF4 integration,
**not an NVIDIA-maintained release**. Original ARDY and LLM2Vec notices are retained.

The release includes actual Core model code, the proven NF4/offload adapters,
Core27 static skeleton data, native MotionCorrection source and a CPython 3.11
Windows x64 wheel, authenticated loopback HTTP, a persistent single-GPU worker,
and isolated offline CPU Chinese translation. No model weights, Conda environment,
user prompts, PMX assets, sessions or credentials are distributed in this source package.

## Install

Use **ARDY Motion Bridge 0.6.0 → Step 1 – AI Environment Setup → Install AI Environment**.
The installer detects/reuses a Conda program or installs a checksum-pinned private
Miniforge JustMe, then creates its own prefix. It does not activate Conda, modify
global PATH, install CUDA Toolkit, compile on the user's machine, or install AI
libraries in Blender. READY requires real CPU translation and NF4/Core27 inference.

The known model and wheel downloads exceed 5 GB; use the shipped deployment
descriptor for exact bytes including pinned Conda base packages. Reserve at least
24 GiB free disk. Downloaded and installed size are separate measurements.

Existing deployments can use **Detect Existing / Import Existing**. Verified
local Core/NF4/translation files are reused without re-downloading. Borrowed
environments are not upgraded or deleted. Fresh weights use:

```
<INSTALL_ROOT>/models/Esheep-ardy-llm2vec_NF4/
<INSTALL_ROOT>/checkpoints/ARDY-Core-RP-20FPS-Horizon40/
```

Model inventories, fixed revisions and SHA256 are in `config/model_sources.json`.
NF4: https://huggingface.co/Esheepbo/Esheep-ardy-llm2vec_NF4

The installer uses the official Hugging Face client with `local_dir` and exact
revisions, stages incomplete downloads, verifies every file and only then
promotes it. Runtime model loading is local and offline. ModelPathResolver uses
the generated runtime JSON, explicit local directories, then install defaults.

## Supported target

Windows x64, AVX CPU, Python 3.11, CUDA-enabled PyTorch 2.11.0+cu128 and a compatible
NVIDIA driver. The verified GPU is RTX 5070 Ti Laptop 12 GiB. At least 8 GiB total
and an estimated 5.75 GiB free/reusable VRAM are preflight thresholds, not a promise
that every NVIDIA card or motion will work. Other devices require actual validation.
The bundled extension uses MSVC runtime DLLs supplied by the Conda/runtime stack;
no Visual Studio Build Tools is required for the shipped ABI.

Private Miniforge bootstrap requires an ASCII directory. An existing Conda may
be used with other paths; Unicode/space compatibility is reported from actual tests.

## Operations

PowerShell can run `installer/install_backend.ps1` using Blender's Python or a
standard Python bootstrap. No ARDY Python environment must already exist.
`install_backend.py --help` lists import/repair/verify/reinstall modes.

`runtime_config.json`, `installation_state.json`, `install.log`, model directories,
environments and outputs are private installation artifacts. Do not commit them.
Repair only changes the installer-owned environment; existing user environments
are never upgraded. Uninstall requires confirmation, retains models/cache/output
by default, and refuses paths outside its ownership manifest.

The HTTP service binds only 127.0.0.1 and uses per-session bearer credentials.
It preserves the existing single-GPU queue, cancellation, NF4 double quantization,
CPU offload, MODEL_INIT_LOCK and strict `allow_pickle=False` Core NPZ protocol.
No user text is sent to a translation provider. Argos zh_en 1.9 runs in a separate
CPU environment with hash-pinned resources and editable/cached English results.

## Source, attribution and publishing

Source lineage: NVIDIA `nv-tlabs/ardy` and the deployed Windows/NF4 community
adaptation from `zwukong/ardy-keyframeMotionGeneration`. This copy preserves the
working deployed source instead of replacing it with a new upstream clone.
See `ATTRIBUTIONS.md`, `LICENSE`, `licenses/` and `PUBLISHING.md`.

Model licenses are distinct from the Apache-2.0 code license. The Core checkpoint
uses NVIDIA's Open Model License. The publisher deferred the NF4 model-card/license
supplement; this source package does not redistribute those weights or claim they
are Apache-2.0. Complete that metadata separately before promoting public use.

The maintainer publishes GitHub commits, the `v0.6.0-backend` tag and release assets
manually. The plugin downloads an exact release asset with a pinned SHA256, not
whatever code happens to be on `main`.

See [中文说明](README.zh-CN.md).
