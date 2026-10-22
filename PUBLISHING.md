# Manual publication of 0.6.0

The maintainer publishes this release manually. No remote commit, tag, or upload
was performed while preparing these files. This directory is the public backend
source, not the original development directory and not a copy of a Conda environment.

## Assets and tag

Repository: https://github.com/HaoboXi/ardy-windows-esheep_optimize

1. Review this clean directory and its `.gitignore`, then commit its contents to
   the repository. Retain `LICENSE`, `ATTRIBUTIONS.md`, source copyright headers,
   `licenses/` and the small prebuilt wheels in `installer/wheels/`.
2. Create the tag **v0.6.0-backend** at the reviewed commit.
3. Create a GitHub Release for that tag. Upload the exact prepared files:
   `ardy-backend-0.6.0.zip`, `ardy-deployment-0.6.0.json`, and `SHA256-v060.txt`.
   The Blender add-on and full source ZIP can be attached as additional assets.
4. The add-on pins the backend ZIP SHA256 and its embedded source-manifest SHA256.
   GitHub's automatically generated source ZIP has a different layout/hash and
   cannot substitute for `ardy-backend-0.6.0.zip`.
5. After upload, independently check the release download SHA256 and perform the
   first install from the published URL. That network end-to-end test is pending
   publication; local source and new-prefix deployment were tested separately.

Do not edit or recompress a release asset after its descriptor has been generated.
Any source/manifest change requires rebuilding the archive and descriptor and
shipping the matching add-on. Keep an existing release immutable; use a new version
and tag for a subsequent build.

## Contents to exclude

Never submit installation roots, `runtime_config.json`, `installation_state.json`,
`session.json`, tokens, prompts, logs, outputs, model weights, PMX/BLEND files,
Python environments, download caches or development reports. There is no copied
Git history or index in this staging directory. Before the first public commit,
review `git diff --cached` and `git status` in your own checkout.

## Dependency provenance

The runtime inventory was extracted from the working Windows deployment and then
reinstalled into a new prefix. Conda supplies pinned Python/base packages through
`config/conda_packages.json`; pip installs hashed Windows wheels from
`config/wheels.json`. The standalone CPU translator uses its own venv and
`config/translation_wheels.json`. Build-only requirements are separate.

The CPython 3.11 Windows x64 MotionCorrection wheel packages the previously
verified MSVC binary; it is not a claim of a new reproducible C++ build. Source,
compiler/ABI, binary SHA256 and imported DLLs are recorded in
`config/native_wheel_manifest.json`. Fresh-prefix imports and real inference
passed without a user C++ compiler or CUDA Toolkit. Different ABIs need their
own publisher-built wheel and validation.

## Model metadata

Model files are downloaded from their original pinned Hugging Face revisions;
none are redistributed in these archives. Core model licensing is separate from
the Apache-2.0 source. The maintainer has deferred the NF4 model-card/license
supplement; the existing notices and this outstanding item remain recorded in
`ATTRIBUTIONS.md`. No new license was invented or applied to those weights.

Translation still uses the previously verified Argos zh_en 1.9 source and hash.
No third-party text translation endpoint is enabled.
