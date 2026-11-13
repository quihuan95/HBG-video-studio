# TASK: Integrate `rea-video` Skill into the Existing The HBG Video Application

> **For:** Codex / Claude Code / Cursor Agent  
> **Mode:** Modify the existing application. **Do not scaffold, replace, or rewrite the application.**  
> **Language for UI and end-user reports:** Vietnamese by default; retain English technical identifiers.  
> **Upstream:** https://github.com/JuneYaooo/rea-video  
> **Related existing requirement (if present):** `AI_FOOTAGE_SOURCE_SEARCH_TASK.md`

## 0. Objective

Add a **Reference Video Breakdown / Reverse Engineering** feature powered by the open-source `rea-video` CLI and its agent skill. An editor supplies a reference video that the app is authorized to process; the feature decomposes it into shots, analyzes production methods, pacing, overlays/captions and audio where available, and shows a reviewable per-shot breakdown. It should then optionally produce **search briefs** for the application's existing internal/Internet footage search so that editors can find licensed or owned replacements and assemble a CapCut-friendly shotlist.

**Important distinction:** `rea-video` analyzes video and explains how to recreate a result; it is **not** itself a Google Drive/YouTube/stock-search provider. Do not claim that it searches the Internet or extracts semantically relevant footage from an arbitrary archive on its own. Implement that as a separate adapter to existing search features, only when such features exist.

## 1. Upstream facts and verification

The following are supported by the public README, `AGENTS.md`, and package manifest available when this task was written:

- Requires **Python >= 3.10** and **FFmpeg**; upstream installation path: `git clone https://github.com/JuneYaooo/rea-video` then `bash scripts/install_skill.sh`, followed by `rea-video --help`.
- The package exposes the `rea-video` CLI (`rea_video.cli:main`), and contains a skill under `skills/rea-video/SKILL.md`, CLI/analysis code in `rea_video/`, docs under `docs/`, and tests/evaluation tooling.
- It analyzes shots, distinguishes possible filmed/AI/code/3D/mixed production, captions/overlays, editing rhythm, and audio; its output includes a rich HTML report (`report.html`), and the repo documents a breakdown JSON artifact. It can run without a vision model but optional vision API/model capabilities improve some judgments.
- It **does not automatically render a finished video** as its core function; optional upstream remake integrations are separate.
- Public repo describes optional `--env-file` for VLM secrets; **never** commit secrets.

**MANDATORY BEFORE IMPLEMENTATION:** Clone or inspect the actual upstream revision in the agent's own development environment; read in this order:

1. `README.md`, `AGENTS.md`, `LICENSE`, `pyproject.toml`
2. `skills/rea-video/SKILL.md` and referenced files
3. `docs/cli.md`, `docs/what-it-detects.md`, `docs/decompose.md`
4. CLI help for real command syntax (`rea-video --help` and relevant subcommand `--help`)
5. Example `report.html`, JSON artifacts and tests to establish the **actual output schema**.

Do **not invent** CLI flags, JSON properties, error codes or runtime contracts. The upstream CLI details and skill file could not be independently fetched in full when this task was authored, so verify all such details locally. Pin the tested git commit in the integration documentation/configuration; report when upstream API/schema differs from assumptions.

## 2. First inspect the EXISTING app (do this before writing code)

- Identify framework, runtime, package manager, current media storage, existing upload/import workflows, data models, auth/permissions, background processing, UI component conventions, settings/config system, search module, Google Drive/media adapters and current export formats.
- Look for `AI_FOOTAGE_SOURCE_SEARCH_TASK.md`, if included; integrate with its existing `search` and `shotlist` contracts instead of implementing duplicate systems.
- Find the existing video/job/detail pages and design the smallest additive integration.
- Inspect deployment environment: Linux, Windows, Docker, shared hosting, managed server, available Python/FFmpeg, mounted directories, GPU and resource limits.
- Produce a brief `docs/rea-video-integration-audit.md` describing what can be reused and any migration/runtime constraints before major changes.

**Constraints:** Do not change framework, auth scheme, styling, data ownership or unrelated business logic. Do not install the upstream agent skill globally on a production host unless explicitly approved. Prefer an isolated sidecar or worker, or existing Python worker if the app already has one. Use version-pinned upstream dependency. Protect other existing features with tests.

## 3. User-facing feature and workflow

### A. Reference video intake

Add an action titled **"Phân tích video tham khảo"** to the existing video/media interface (location based on current UX). Allow:

- Upload or choose an already available local/Google Drive file, subject to authorization and existing permissions.
- Import a public link **only if** the existing app/provider supports authorized acquisition and the URL can be safely fetched; do not scrape protected platforms or bypass access controls.
- Input optional project title, analysis language (default Vietnamese), reference purpose (editing style / shot structure / captions / music / complete), and approval to send frames/video to a third-party model (off by default).
- Display analysis status: `queued`, `processing`, `needs_review`, `completed`, `failed`, `cancelled` as applicable. Reuse app's own statuses if already established.

### B. Run rea-video analysis

- Check `ffmpeg`, Python and real CLI availability before launching; fail with actionable diagnostic if absent.
- For untrusted media use an isolated process/container, strict file/CPU/memory/time limits, safe absolute paths, no shell string concatenation, and an allowlisted working directory.
- Process with the actual supported `rea-video` command (derived from `--help`). Store input media ID, job ID, tool version/commit, exit status, timestamps, warnings, and output artifacts.
- Save machine-readable results when provided by upstream and store the HTML report in protected storage. Sanitize/report sandboxing before embedding HTML. Do not serve raw third-party HTML inside the application's privileged origin; prefer a sandboxed viewer or parsed in-app UI.
- Support offline/tools-only operation; make optional video-capable model mode explicitly configurable. Use the app's secret manager / environment injection; never log API keys.
- Ensure repeat jobs use a file hash + analysis config + upstream version key for optional caching, with a manual **Reanalyze** action.

### C. Reviewable breakdown

A Video Breakdown page should present, to the extent reliably exposed by upstream:

- Overview: input duration, resolution, shot count, processing mode, summary and confidence/uncertainties.
- Timeline: shot start/end in **source video**, ordered strictly by time.
- Per-shot card: representative frame, production-method hypothesis (filmed / AI / 3D / code / screen / mixed / unknown), evidence, camera/motion, lighting/style if available, transitions and visual notes.
- Overlay and subtitle data: text, start/end, placement/style when available; optional SRT/ASS export only if format/timing are actually supported.
- Audio notes: voice/music/effects observations, BPM/sound event timing only when measured or reported; distinguish measured data from inferred interpretation.
- Ability to mark shot status `accepted`, `needs_review`, `rejected`, adjust source IN/OUT manually, and add editor notes without mutating the immutable original analysis artifact.
- A one-click **Open original report** view if `report.html` exists.

**Do not present AI/filmed classification as forensic certainty**: upstream can be wrong on platform-recompressed clips. Surface conflicting and low-confidence evidence and support manual override. Don't claim original authoring model, camera, music license or generation provenance as fact unless metadata/evidence supports it.

### D. Connect to footage search (existing or separately implemented)

Per accepted reference shot, derive a **Footage Search Brief**:

- What appears on screen; key subjects, action, context, lighting, shot type/movement, target aspect ratio and target duration.
- `query_vi`, `query_en`, optional excluded terms and must-have visual attributes.
- Suggested source order: **The HBG authorized internal footage first**, then licensed stock, then clearly labeled external reference links. Respect existing source permissions.
- Search result cards must preserve their real `source_asset_id`, URL/provider, use rights and optional validated `source_in_seconds` / `source_out_seconds`. **Never copy reference-video timestamps onto unrelated candidate footage.**
- If search APIs/adapters are not installed, implement only a **Search this shot** contract/UI stub or export a search brief that the existing search agent can consume. Do not fake results or silently create a new search product.
- Link resulting selected asset back to the reference shot, with editor's selection and provenance audit.

### E. CapCut-oriented handoff

The current editor uses **CapCut Desktop**. Export a zip/organized directory, limited to media that the app has permission to download/copy:

```
project_export/
  README.txt
  shotlist.csv
  breakdown.json
  reference_report.html        # optional, safely preserved
  selected_clips/
    001_scene.mp4
    002_scene.mp4
  thumbnails/
  captions.srt                 # optional, only if validated
```

`shotlist.csv` should include at minimum:

`scene_order, reference_start_seconds, reference_end_seconds, desired_duration_seconds, visual_brief, selected_source_name, selected_source_url_or_id, selected_source_in_seconds, selected_source_out_seconds, rights_status, reviewer_status, notes`

Distinguish **reference timecodes**, **replacement footage source timecodes**, and **future edit timeline timecodes** in all models and UI. Export reference analysis even if no replacement footage has been selected. Do not assume direct EDL/XML import or undocumented CapCut project-file manipulation works. Pretrim MP4 only with authorized source access and preserve original file untouched.

## 4. Suggested integration contracts (adapt to existing app, not mandatory routes)

Do not create these endpoints verbatim if the existing API already offers equivalent capabilities; preserve established conventions.

```
POST   /api/video-analyses              # create analysis of authorized video
GET    /api/video-analyses/{id}         # job/detail/status
GET    /api/video-analyses/{id}/shots   # normalized shot list
PATCH  /api/video-analyses/{id}/shots/{shotId}/review
POST   /api/video-analyses/{id}/retry
POST   /api/video-analyses/{id}/shots/{shotId}/search-brief
POST   /api/video-analyses/{id}/shots/{shotId}/select-footage
GET    /api/video-analyses/{id}/export  # generated output or job link
```

Suggested normalized **internal** records (not upstream schema):

```
VideoAnalysis {
  id, project_id, source_asset_id, user_id, status,
  upstream_commit, tool_version, analysis_config,
  started_at, completed_at, error_code,
  raw_artifact_paths, summary, created_at
}

ReferenceShot {
  id, analysis_id, index,
  reference_in_seconds, reference_out_seconds,
  visual_description, production_method,
  evidence_json, confidence_or_review_reason,
  thumbnail_path, overlays_json, audio_notes_json,
  reviewer_status, reviewer_notes
}

ShotFootageSelection {
  id, reference_shot_id, source_asset_id,
  source_in_seconds, source_out_seconds,
  rights_status, selection_notes, selected_by, selected_at
}
```

Add migrations only for missing data. Prefer existing media/shotlist models and field naming. Make the upstream-to-normalized parser a dedicated adapter with schema/version validation; preserve raw artifacts for debugging. If a field is absent, keep it null/unknown rather than invent a value.

## 5. Task execution and robustness

1. Inspect app and upstream; document version, supported commands and output sample.
2. Implement an isolated `ReaVideoAdapter` boundary (process invocation + validation + artifact parser) and unit tests with fixtures based on **real** upstream output.
3. Add asynchronous background execution with progress/status that matches existing queue facilities. A request must not block until a full video finishes. If queue infrastructure does not exist, add the lightest maintainable solution consistent with the host.
4. Add a secured read-only analysis viewer and shot-review controls.
5. Add per-shot footage-search handoff to existing internal/Internet search module when available.
6. Add shotlist/CapCut export and end-to-end tests.
7. Update README, deploy configuration, environment variables and operational instructions.

Security and privacy requirements:

- Strict upload type/size/duration limits (configurable); use `ffprobe` to validate media, not extension alone.
- Prevent path traversal, URL-based SSRF, malicious redirects and access to private IP ranges from arbitrary user-provided URLs.
- Never give untrusted paths directly to shell interpolation, never run privileged containers, and apply per-job disk/time/process quotas.
- Authorization checks for uploads, Drive access, preview files, analysis reports, search briefs and exports.
- Explicit opt-in before cloud transmission of internal/customer footage; redact logs and restrict retention of temporary data.
- No automated copying/reposting of copyrighted third-party video; analyze references only when authorized and use independent/owned/licensed source for production.

## 6. Acceptance criteria / tests

- [ ] App starts exactly as before and pre-existing user flows remain functional.
- [ ] An authorized local MP4 can be analyzed, using the **actual tested** upstream command, and job status updates correctly.
- [ ] At least one real output is parsed into shot cards with correct numeric source timecodes; `0 <= start < end <= duration` (allow small container-timestamp tolerance if documented).
- [ ] Unsupported/missing data displays as unknown rather than fabricated values.
- [ ] Results and logs are scoped to the user/project; another unauthorized user cannot retrieve them.
- [ ] Failure cases covered: invalid video, missing FFmpeg, CLI exit nonzero, timeout, no disk, parser/schema mismatch, failed optional VLM.
- [ ] Analysis stays usable without optional VLM API credentials.
- [ ] Reference timestamps and selected replacement source timestamps are never conflated.
- [ ] If existing footage search is present, at least one shot brief successfully invokes it and links a chosen licensed candidate.
- [ ] CSV/ZIP export opens; a pretrimmed MP4 is playable; SRT, if exported, has valid ascending timestamps.
- [ ] No source footage is modified in place and no AI API keys appear in git/logs.
- [ ] Existing project lint/test/build succeeds. Run upstream tests only if modifying upstream itself; ideally keep upstream vendor code unmodified.

## 7. Definition of done and agent report

Return a concise implementation report including:

1. App framework and modules reused.
2. Exact pinned `rea-video` commit/version, CLI commands actually tested and supported artifact structure.
3. Files changed, database migrations, config flags, and installed runtime dependencies.
4. Working end-to-end steps: import -> analyze -> review -> search brief -> choose source -> CapCut export.
5. Test/build results, performance observed on a representative sample (report hardware and video length).
6. Known limitations (especially source licenses, classification confidence, captions/audio availability, optional cloud costs).
7. Any features deferred because search APIs, permission to access footage, or compatible runtimes are unavailable.

## 8. Suggested user prompt to start the coding agent

> Read `REA_VIDEO_INTEGRATION_TASK.md` in full, then audit my existing app and the current upstream `https://github.com/JuneYaooo/rea-video`. Integrate its reverse-video-analysis capability as an additive feature using the actual documented CLI and output schema. Reuse my app's authentication, storage, jobs, media search and shotlist mechanisms. Do not create a new app. First deliver an architecture audit, then implement and test the minimal end-to-end path. Treat `AI_FOOTAGE_SOURCE_SEARCH_TASK.md`, if present, as the footage-search requirements; `rea-video` is the reference-analysis engine, not a search API. Return code changes and test evidence, not only advice.

## 9. Upstream sources

- https://github.com/JuneYaooo/rea-video
- https://github.com/JuneYaooo/rea-video/blob/main/AGENTS.md
- https://github.com/JuneYaooo/rea-video/blob/main/pyproject.toml
- https://github.com/JuneYaooo/rea-video/blob/main/skills/rea-video/SKILL.md
- https://github.com/JuneYaooo/rea-video/blob/main/docs/cli.md
- https://github.com/JuneYaooo/rea-video/blob/main/docs/what-it-detects.md

> This task file is an **integration specification**, not a copy of the upstream skill. Follow the actual pinned upstream documentation and repository license, not assumptions in this document, where they disagree.
