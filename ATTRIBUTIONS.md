# Source and model attribution

- ARDY source and MotionCorrection: Copyright (c) 2026 NVIDIA CORPORATION &
  AFFILIATES. Apache-2.0; original `LICENSE` and SPDX headers retained.
  https://github.com/nv-tlabs/ardy
- Deployed community NF4 adaptation: https://github.com/zwukong/ardy-keyframeMotionGeneration
  (deployed source lineage 883d44caa99f291b2b37498a09da3c21c65f9244).
- Vendored LLM2Vec portions: Copyright (c) 2024 McGill NLP, MIT; full original
  notice in `licenses/UPSTREAM_ATTRIBUTIONS.md` and source headers.
- Existing Unitree BSD notices are retained in `licenses/UPSTREAM_ATTRIBUTIONS.md`.
  This release supports Core27 PMX/MMD, not a new G1/FBX/VRM workflow.
- Native wheel: same verified Windows MSVC MotionCorrection binary and C++ source.
  Eigen MPL-2.0-only headers and pybind11 BSD-3-Clause notices accompany the wheel.
  No CUDA extension build is required. ANTLR runtime is shipped as a pure Python
  wheel with its BSD-3-Clause notice. See `licenses/`.
- Core model: NVIDIA ARDY-Core-RP-20FPS-Horizon40, fixed revision in
  `config/model_sources.json`; NVIDIA Open Model License applies separately.
  Weights are fetched from NVIDIA, not committed or redistributed in source archives.
- NF4 model: Esheepbo/Esheep-ardy-llm2vec_NF4, hash-identical to the deployed NF4
  files; earlier source Aero-Ex/KIMODO-Meta3_llm2vec_NF4. LLM2Vec/Meta Llama 3
  lineage is distinct from the ARDY Apache-2.0 code license. The maintainer
  deferred the model-card/license supplement. This document does not grant model
  rights or label those weights Apache-2.0. No NF4 weights are included here.
- Offline translation: Argos zh_en 1.9, based on OPUS-MT (Jörg Tiedemann and
  Santhosh Thottingal, EAMT 2020), original package README identifies CC-BY 4.0.
  CTranslate2 and SentencePiece are separately installed dependencies, not new LLMs.
  Source: https://github.com/argosopentech/argos-translate
- Miniforge, Conda, PyTorch, bitsandbytes and Python packages retain their own
  licenses. Their pinned upstream binaries are downloaded by the installer;
  no developer environment or CUDA Toolkit is copied into this repository.

The integration retains NF4 double quantization, CPU offload and MODEL_INIT_LOCK.
Windows deployment, local service, installer and Blender bridge changes are
community additions; this release is not maintained or endorsed by NVIDIA.
