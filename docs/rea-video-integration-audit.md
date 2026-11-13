# REA Video integration audit

## Existing application

- Runtime: FastAPI/Python worker, SQLite, React 19 + TypeScript/Electron, FFmpeg/FFprobe.
- Reusable media layer: `footage_source` and `footage_asset` already represent authorized local and Google Drive videos. `footage_analyzer._materialize` safely resolves those sources without arbitrary URL fetching.
- Reusable search layer: `footage_research_jobs`, shots, candidates, selection and CapCut media-package export already separate internal, licensed stock and external-reference provenance.
- Job model: the app persists state in SQLite and uses background asyncio tasks for long-running local work. REA analysis follows that pattern and survives in a diagnosable state; interrupted `PROCESSING` records become retryable failures on startup.
- Security boundary: the backend binds to localhost and currently has no user authentication. This integration therefore accepts only an existing `footage_asset`, not an arbitrary filesystem path or URL. Authorization remains the profile/source ownership already used by the desktop app.

## Upstream verified contract

- Repository: `https://github.com/JuneYaooo/rea-video`
- Pinned commit: `356815c0d61291811551a2b8813b2b571d9b3238`
- Package: `rea-video==0.1.0`, Apache-2.0, Python >=3.10.
- Tested CLI: `rea-video decompose VIDEO -o OUT [--vlm|--no-vlm] [--lang zh|en] [--workers N] [--no-stems]`.
- Machine artifact: `breakdown.json`, schema `rea_video.breakdown.v1`. Relevant stable fields are `source`, `summary`, `analysis.vlm`, and ordered `shots[]` containing `index`, `start`, `end`, `duration`, `base`, `assets`, `aspects`, `overlay`, `text`, `vlm`, and `replication`.
- Other preserved artifacts: `report.html`, `report.md`, `storyboard.jpg`, `shots/`, optional `packaging/` and `stems/`.

## Runtime decision

REA Video is installed in an isolated sidecar virtualenv under
`output/_shared/rea-video-runtime`. It is not installed into the application
environment and its skill is not linked globally, avoiding OpenCV dependency
conflicts. The runtime command is configurable with `REA_VIDEO_CLI`.

VLM transmission is off by default. Enabling it requires both explicit request
approval and `REA_VIDEO_ALLOW_VLM=1`; credentials are supplied through a
separate environment file path and are never read back or logged by the app.

## Additive migration and constraints

New tables store immutable analysis artifacts, normalized reference shots and
review overrides. Reference timecodes remain separate from replacement-source
timecodes. HTML is downloadable/opened as a separate file and is never injected
into the privileged React origin.

The first offline run may download REA Video's audio-separation model. Analysis
is CPU-heavy and intentionally limited to one concurrent process with a
configurable timeout and input-size/duration limits. Vietnamese UI is supported,
while upstream report generation uses English because upstream currently only
supports `zh` and `en`.
