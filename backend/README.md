## v0.6.0 deployment

Runtime paths now come from the installer-generated configuration. The clean public backend includes an independent bootstrap, exact manifests and local model resolution. See the release source README and PUBLISHING.md.

# Windows ARDY local service 0.5.1

The Blender add-on starts this service with its existing Conda Python. It never
imports Core, Torch, bitsandbytes or CUDA in Blender. The NF4 environment is unchanged.
Source of truth: this `backend/` directory; the package builder copies it into
`ardy_motion_bridge/backend_service/` in the install ZIP.

The service is stdlib-only; its single persistent child imports the existing
the selected installation source/weights. Only the child owns the GPU. It preserves NF4,
double quantization, CPU offload, CFG=(2,2), 10 diffusion steps and native
postprocessing. Model loading is lazy; READY means HTTP ready, not weights ready.

v0.5.1 adds authenticated `POST /translate {"text":"..."}` and
`GET /translation/status`. Translation uses a separate, lazy CPU subprocess in
`<project>/translation_cpu_v051`, with the Argos zh_en 1.9 CTranslate2 model.
No Torch, Stanza or large LLM is installed there. Run the source distribution's
`tools/setup_translation_v051.py` once to install isolated, pinned dependencies.
Prompts never go to a remote translation service. English bypasses MT unchanged.
The backend session owns its CPU child, closes it on shutdown, and caches results
under its local `translation_cache`; cache keys include the engine revision.
`NEEDS_REVIEW` results must be corrected/confirmed in Blender before generation.
The existing `/generate` contract, worker protocol and inference settings are unchanged.

Start through Blender or `backend_client.start_backend()`. Manual advanced use:
`<Conda Python> -I backend/server.py --config <trusted local launch.json>`.
Configuration keys: project_root, python, data_root, session_dir, port, idle_seconds.
Use native Windows absolute paths. There are no arbitrary API paths or commands.

GET /health, GET /capabilities, POST /generate,
GET /jobs/{uuid}, POST /jobs/{uuid}/cancel, GET /jobs/{uuid}/result,
POST /shutdown. All require the random session bearer credential stored under the
current user's LocalAppData/ARDYMotionBridge/session.json. Never commit, email or
bundle that file. Rejects browser Origin, unexpected Host and non-loopback clients.

Generate body: {"prompt":"A person walks forward naturally.",
"max_duration_seconds":3.0,"seed":42}. No other fields are accepted. 16 queued or
running requests maximum, 0.05..10 seconds each, native FPS 20. History-probe is a
fixed internal diagnostic endpoint, not a production conditioning mode.

Each UUID folder contains durable job.json, immutable raw.npz, separately validated
motion.npz and optionally a cancellation flag. Raw and trimmed hashes are reported.
Cancelled/failed jobs are not published as results. A prior successful result is
never removed when a later request fails. Inspect server.log and jobs/worker.log.

Project and GPU locks live in the current user's common runtime lock directory,
independent of per-client session directories. Running cancellation checks between
denoising iterations; after 8 seconds the service terminates only its owned child.
OOM/native exit/600-second deadline cause worker restart on the next job.
The native SciPy BLAS import precedes worker reader threads; GPU sampling runs in
the parent process to avoid the Windows DLL-loader deadlock found during testing.

Closing a panel has no lifecycle effect. Closing Blender leaves the independent
service available for up to 300 seconds without requests/jobs, then it shuts down
and releases the model. Stop ARDY Backend requests immediate orderly shutdown.
The per-user runtime/cache remains on disk; no automatic asset deletion occurs.

Before generation the worker checks free/reusable GPU memory against an audited
5.75 GiB estimate (including headroom). Low capacity is rejected before model
loading with GPU_BUSY_CAPACITY; this heuristic does not guarantee against OOM.
