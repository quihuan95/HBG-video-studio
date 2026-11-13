# TASK: Tích hợp AI Footage Source Search vào ứng dụng hiện tại

> **Vai trò:** Bạn là coding agent (Codex / Claude Code / Cursor Agent) đang làm việc **trực tiếp trong repository hiện có**.
>
> **Mục tiêu:** Bổ sung tính năng tìm kiếm source footage phục vụ dựng video cho The HBG: nhận kịch bản/voice-over, tự tách thành các cảnh, tìm nguồn trong thư viện nội bộ và trên Internet, đưa ra các lựa chọn phù hợp kèm timestamp có căn cứ, rồi xuất shotlist và clip để editor sử dụng trong CapCut.
>
> **QUAN TRỌNG:** Đây là yêu cầu **nâng cấp app đang có**, **KHÔNG phải dự án mới**. Không scaffold app mới, không thay framework, không tự ý viết lại hệ thống hoặc thay đổi các chức năng hiện hữu.

---

## 0. Nguyên tắc thực thi bắt buộc

1. **Khảo sát code trước khi sửa.** Tự xác định stack, thư mục, module, auth, DB, job queue, storage, AI service, UI component, conventions, tests, cách deploy và các chức năng video/media đã có.
2. **Tái sử dụng tối đa:** service tìm kiếm, LLM, Google Drive/Cloud Storage, upload, video editor, task queue, media library, database, config và UI pattern có sẵn. Chỉ tạo component/service/migration mới khi thực sự thiếu.
3. **Không hardcode** API key, token, model, URL, folder ID, đường dẫn local hoặc quyền truy cập. Dùng cấu hình / environment tương thích app.
4. **Không làm hỏng app:** không xóa schema hoặc data, không thay đổi breaking API, không sửa module không liên quan, không ghi đè cấu hình production. Migration phải an toàn và có kế hoạch rollback.
5. **Giữ nguyên xác thực và phân quyền.** Chỉ truy cập footage mà người dùng/ứng dụng được cấp quyền; không đưa video nội bộ, dữ liệu khách hàng hoặc thông tin nhạy cảm lên AI/cloud bên thứ ba nếu chưa có cấu hình cho phép.
6. **Không giả tạo kết quả.** Không tự bịa URL, nội dung cảnh, timestamp, license, tên chương trình hoặc điểm tin cậy. Không đủ dữ liệu thì hiển thị `UNVERIFIED` / `NEEDS_REVIEW`.
7. **Không vượt bảo vệ của website:** không bypass login, CAPTCHA, DRM, rate limit; không scrape trái điều khoản. Nguồn online phải lưu URL nguồn và tình trạng quyền sử dụng.
8. **Có thể triển khai từng phần.** Tính năng không được phụ thuộc cứng vào một nhà cung cấp API. Dùng adapter/interface và degradation hợp lý.
9. **Thực hiện code thật** trong repo sau khảo sát (không chỉ mô tả). Nếu thiếu credential/hạ tầng, hoàn thiện phần có thể chạy bằng mock/test fixture, đánh dấu phần chờ cấu hình, không giả vờ tích hợp thành công.
10. **Không tự động download hay publish footage online** khi chưa xác định được quyền sử dụng. Cho phép preview/link tham khảo và xác minh thủ công.

## 1. Bắt đầu bằng audit repository

Trước khi viết code, thực hiện:

- Đọc `README`, hướng dẫn dev, config, schema/migration, các module AI, video, file storage, Google Drive và search hiện hữu.
- Xác định entrypoint chức năng này sẽ xuất hiện tại đâu trong UI và quyền truy cập cần có.
- Kiểm tra đã có các integration nào: OpenAI/Claude, Drive, search API, FFmpeg, vector index, queue, subtitle, CapCut export.
- Ghi một **bản kế hoạch thay đổi ngắn** trong phản hồi agent: file/module sẽ đụng tới, chức năng có thể tái sử dụng, migration cần thiết, các rủi ro. Sau đó triển khai mà không đòi tạo dự án mới.
- Nếu repo chưa có tích hợp Google Drive hoặc provider tìm kiếm Internet, xây interface + cấu hình + UI trạng thái `NOT_CONFIGURED`; không tự đoán credentials.

## 2. User flow (end-to-end)

1. Người dùng vào màn hình **AI Footage Search** có sẵn hoặc được thêm vào navigation phù hợp.
2. Nhập/paste **kịch bản video hoặc voice-over**; tùy chọn nhập thời lượng mục tiêu (ví dụ 30–90 giây), tỷ lệ khung hình (mặc định 9:16), chủ đề và ưu tiên nguồn.
3. Nhấn **Phân tích kịch bản**. AI chia thành các beat/shot gợi ý, trích lời thoại tương ứng, thời lượng dự kiến, visual intent và bộ keyword Việt/Anh.
4. Nhấn **Tìm footage**. Hệ thống tìm đồng thời hoặc theo chính sách ưu tiên: **(A) kho nội bộ The HBG → (B) nguồn Internet được cấu hình**.
5. Hiển thị **2–5 lựa chọn/source cho mỗi shot** nếu có, gồm thumbnail, mô tả thực tế, nguồn, độ dài, độ phù hợp, thời gian `source in/out` (nếu đã xác minh), link mở source, bản quyền/trạng thái kiểm chứng.
6. Người dùng preview, chọn/đổi source, sửa thời gian IN/OUT, thêm ghi chú cho editor, đánh dấu `APPROVED` hoặc `NEEDS_REVIEW`.
7. Xuất **shotlist CSV/JSON** và **CapCut media package** gồm clip MP4 đã cắt **nếu có file gốc và quyền xử lý**, tên file theo thứ tự `001_...mp4`, kèm `README.md` và có thể kèm SRT nếu có phụ đề. Nếu không có quyền tải, chỉ export URL + timecode và thông báo rõ.
8. Lưu lịch sử các job / lựa chọn để người dùng quay lại chỉnh sửa.

## 3. Phân tích kịch bản (Script-to-Shot Plan)

- Tái sử dụng LLM client và model configuration hiện có; không khóa vào một tên model cụ thể.
- AI trả về **structured output** có validation (JSON Schema / Pydantic / Zod theo stack), không parse tự do nếu framework hỗ trợ cấu trúc.
- Mỗi shot tối thiểu gồm:
  - `shot_id`, `order`, `script_excerpt`, `visual_description`, `visual_intent`
  - `keywords_vi[]`, `keywords_en[]`, `negative_keywords[]` (được suy ra từ ngữ cảnh kịch bản, không phải rule lọc lead)
  - `target_duration_seconds`, `timeline_start_seconds`, `timeline_end_seconds`
  - `priority` và `notes`
- Phân biệt footage **chứng minh hoạt động thật** (dự án/sự kiện cụ thể của The HBG) với footage **minh họa chung**. Không cho phép nguồn stock bị trình bày như footage thật của dự án.
- Người dùng có thể chỉnh shot plan trước/sau khi search. Phần thời lượng timeline là **ước tính để dựng**, không phải timestamp của nguồn gốc.

## 4. Search nội bộ (The HBG media library / Google Drive)

### 4.1 Khám phá và kết nối

- Ưu tiên dùng media library/storage đã có trong app. Nếu đang có Google Drive OAuth/service account, tái sử dụng theo quyền thực tế.
- Chỉ quét các folder/user scope được cấu hình; có pagination, incremental sync, dedupe theo `provider + file_id`, kiểm soát rate limit, trạng thái và lỗi quyền.
- Lưu metadata: `asset_id`, `provider`, `provider_file_id`, `name`, `mime`, `size`, `duration`, `width`, `height`, `created_at`, `modified_at`, `source_url`, `access_status`, `index_status`, `checksum` nếu có.

### 4.2 Index footage

- Với file được phép xử lý, dùng engine hiện có hoặc FFmpeg/ffprobe để đọc metadata, tạo thumbnail/proxy và scene segmentation. Không yêu cầu tải toàn bộ kho ngay lập tức.
- Đối với video, lưu **segment/cảnh theo thời gian**: `segment_start_seconds`, `segment_end_seconds`, mô tả hình ảnh, tags, transcript/từ khóa nếu có, `index_version`, trạng thái xác minh.
- Nếu đã có embeddings/vector DB thì tái sử dụng. Nếu chưa, làm **MVP metadata + transcript + sampled keyframe descriptions** trước; vector search là nâng cấp tùy chọn, không mặc định dựng thêm hệ thống lớn.
- Nếu có TwelveLabs hoặc video understanding API khác được cấu hình, đặt sau provider adapter; không gửi video nội bộ lên cloud nếu `ALLOW_EXTERNAL_VIDEO_PROCESSING` chưa bật.
- Có job status: `PENDING`, `PROCESSING`, `READY`, `FAILED`, `SKIPPED`; retry/backoff, giới hạn concurrency và cleanup temporary files.
- Cập nhật khi file thay đổi; không reindex file không đổi.

### 4.3 Trả kết quả

- Search cả tên file/metadata, nội dung transcript, mô tả phân đoạn và semantic index nếu có.
- Ưu tiên kết quả **đúng bối cảnh, đúng sự kiện, đúng thời điểm, đúng cảnh**; `source_in/out` lấy từ timestamp segment có thật.
- Không khẳng định footage thuộc dự án cụ thể chỉ vì mô tả trùng keyword. Trả `verification_status` và `evidence` tương ứng.
- Hỗ trợ tìm trong kho ngay cả khi cloud AI bị tắt.

## 5. Search Internet (external footage)

- Dùng các adapter theo công cụ/API **đã cấu hình hợp lệ**: stock video providers, YouTube metadata/search, web search; không hardcode scraping không chính thức.
- Ưu tiên stock footage được phép sử dụng; nguồn YouTube/website khác chỉ được xem là **reference** trừ khi license/quyền sử dụng được xác minh.
- Kết quả tối thiểu: `provider`, `title`, `source_url`, `preview_url` (nếu được phép), `thumbnail_url`, `duration_seconds` (nếu biết), `creator`, `license_status`, `attribution`, `download_allowed`, `retrieved_at`.
- Với nguồn video online, chỉ xuất timestamp khi có dữ liệu segment/transcript/video analysis thực tế. Nếu không, để `source_in/out = null` và `timestamp_status = UNVERIFIED`.
- Link tìm kiếm không đồng nghĩa với đã xác thực nội dung video. Cần thể hiện rõ trong UI.
- Có cache kết quả, timeout, retry/backoff, pagination và chỉ báo provider chưa cấu hình / hết quota / lỗi mạng.
- Dedupe theo canonical URL/provider ID. Hạn chế kết quả lặp giữa các shot.
- Khi internet unavailable, phần internal search vẫn chạy bình thường.

## 6. Logic xếp hạng kết quả

Tạo scoring dễ hiệu chỉnh bằng config; ví dụ ban đầu (cần kiểm thử trên dữ liệu thật):

- Semantic / visual match: 40%
- Đúng bối cảnh và tên sự kiện/chương trình: 25%
- Chất lượng source và khung hình phù hợp: 10%
- Thời lượng cảnh phù hợp: 10%
- Mức độ tin cậy & khả năng sử dụng: 15%

**Nguyên tắc:** Không cho kết quả sai sự kiện thắng chỉ nhờ keyword. Với shot cần proof về dự án cụ thể, nếu thiếu source nội bộ đã xác minh thì báo **không tìm thấy footage chứng thực**, có thể đề xuất generic B-roll riêng có nhãn `ILLUSTRATIVE_ONLY`.

Score là **điểm xếp hạng**, không được hiển thị như xác suất chắc chắn trừ khi có hiệu chuẩn thực tế.

## 7. Timestamp: tiêu chuẩn dữ liệu bắt buộc

Phân biệt hai hệ thời gian:

- `timeline_start_seconds`, `timeline_end_seconds`: vị trí dự kiến của shot trong video thành phẩm.
- `source_start_seconds`, `source_end_seconds`: vị trí thực tế cần trích từ **video gốc**.

Validation:

- `0 <= source_start < source_end <= source_duration` nếu biết duration.
- Nếu chưa phân tích được video: `source_start = null`, `source_end = null`, `timestamp_status = UNVERIFIED`.
- Chỉ dùng `timestamp_status = VERIFIED` nếu timestamp được lấy từ nguồn có căn cứ và được xác minh bằng preview/analysis thích hợp; có trường `timestamp_evidence`.
- Với video có offset khi tạo proxy, phải mapping đúng về timecode của file gốc.
- Lưu timecode dưới dạng **giây số thực** nội bộ; hiển thị `HH:MM:SS.mmm` ở UI. Không trộn timestamp comment hoặc metadata ngày cập nhật với thời gian bên trong video.
- Trim bằng FFmpeg phải kiểm tra seek mode, tính chính xác frame và kiểm chứng độ dài clip output; không hứa frame-perfect khi chỉ stream-copy.

## 8. UX tối thiểu

Màn hình tương thích UI design hiện tại, gồm:

- Khung nhập script + tùy chọn duration, aspect ratio, ưu tiên `Internal first` / `Mixed` / `External only`.
- Danh sách shot theo thứ tự, có sửa nội dung/keywords.
- Search progress và lỗi theo từng provider.
- Result cards hiển thị thumbnail, source, title, description, duration, source in/out, fit score, `LICENSE: VERIFIED / UNKNOWN / RESTRICTED`, `TIMESTAMP: VERIFIED / UNVERIFIED`.
- Preview clip (khi nguồn hỗ trợ), link mở source, chọn phương án A/B/C, nhập note cho editor.
- Nút `Export Shotlist` và `Export CapCut Media Package` chỉ khả dụng với dữ liệu đáp ứng điều kiện tương ứng.
- Trạng thái rỗng rõ ràng; không tạo demo result giả trong production.

## 9. Cấu trúc dữ liệu: mở rộng schema hiện có, KHÔNG tạo DB mới nếu không cần

Dùng bảng/collection của app nếu phù hợp; chỉ thêm entity khi thiếu. Các khái niệm tối thiểu:

### FootageAsset
`id, provider, provider_file_id, source_url, title, mime_type, duration_seconds, width, height, file_size, modified_at, license_status, download_allowed, access_status, index_status, metadata_json`

### FootageSegment
`id, asset_id, source_start_seconds, source_end_seconds, description, transcript, tags_json, embedding_ref, timestamp_status, timestamp_evidence, index_version`

### FootageResearchJob
`id, user_id, project_id(nullable), script_text, target_duration_seconds, aspect_ratio, source_preference, status, error_json, created_at, updated_at`

### ShotPlan
`id, job_id, order_index, script_excerpt, visual_description, keywords_json, timeline_start_seconds, timeline_end_seconds, requirement_type, status`

### ShotCandidate / ShotSelection
`id, shot_id, asset_id(nullable), segment_id(nullable), external_source_json(nullable), source_start_seconds(nullable), source_end_seconds(nullable), fit_score(nullable), verification_status, license_status, selected, editor_note`

**DB:** add indexes theo `provider_file_id`, `job_id`, `asset_id`, `status`; giữ FK, soft-delete/tenant boundary theo conventions hiện hữu. Dùng migrations additive, không drop dữ liệu.

## 10. API endpoints: chỉ là contract tham khảo, tuân thủ routing của app hiện tại

- `POST /api/footage-research/jobs` — tạo job từ script.
- `GET /api/footage-research/jobs/:id` — trạng thái job và shot plan.
- `POST /api/footage-research/jobs/:id/analyze` — phân tích script.
- `PATCH /api/footage-research/shots/:id` — chỉnh shot.
- `POST /api/footage-research/jobs/:id/search` — search sources, idempotent hoặc có request key.
- `GET /api/footage-research/shots/:id/candidates` — kết quả theo shot.
- `PATCH /api/footage-research/shots/:id/selection` — chọn source và in/out.
- `POST /api/footage-research/internal/sync` — admin/manual sync, theo permissions.
- `GET /api/footage-research/jobs/:id/export?format=csv|json` — shotlist.
- `POST /api/footage-research/jobs/:id/export-media` — tạo media package bất đồng bộ.

Tái sử dụng authentication, request validation, API convention, route prefix và job architecture hiện hữu. Không mở endpoint nguy hiểm công khai. Chống SSRF khi backend fetch URL, giới hạn domain/size/type và kiểm tra quyền file.

## 11. Export phục vụ CapCut Desktop

**Không phụ thuộc API CapCut hoặc định dạng project private chưa được xác minh.** MVP cần:

```
TheHBG_ProjectName_YYYYMMDD/
  shotlist.csv
  shotlist.json
  README.md
  media/
    001_checkin.mp4
    002_backstage.mp4
    003_conference_hall.mp4
  subtitles/
    captions.srt          # chỉ khi đã có transcript/subtitle hợp lệ
```

- MP4 chỉ xuất khi source được phép truy cập, tải và chỉnh sửa.
- Giữ tên file nhất quán theo thứ tự shot; nếu một cảnh chưa có media, ghi rõ `MISSING_MEDIA` trong shotlist, không xuất clip rỗng giả.
- CSV có các cột: `shot_order, script_excerpt, timeline_in, timeline_out, visual_description, source_type, source_title, source_url, source_in, source_out, timestamp_status, license_status, selected_file, editor_note`.
- `README.md` mô tả cách import `media/*` vào CapCut và sắp xếp theo `shot_order`; SRT được import riêng khi CapCut hỗ trợ trên phiên bản dùng thực tế.
- Không cam kết tự tạo project CapCut có timeline chỉnh sửa sẵn. `roughcut.mp4` là tùy chọn, không thay cho các clip rời.

## 12. Cấu hình ví dụ (đặt vào env example của app, chỉ thêm cái thực sự cần)

```
FOOTAGE_SEARCH_ENABLED=true
FOOTAGE_INTERNAL_ENABLED=true
FOOTAGE_EXTERNAL_ENABLED=true
FOOTAGE_SOURCE_PRIORITY=internal_first
FOOTAGE_DEFAULT_ASPECT_RATIO=9:16
FOOTAGE_INDEX_MAX_CONCURRENCY=2
ALLOW_EXTERNAL_VIDEO_PROCESSING=false
FOOTAGE_TEMP_DIR=/app/storage/tmp/footage
# Provider credentials: reuse existing keys/config. Never commit secrets.
# DRIVE_FOLDER_IDS=...
# VIDEO_ANALYSIS_PROVIDER=...
# STOCK_VIDEO_PROVIDER=...
```

Nếu app có biến môi trường tương đương, **không tạo biến mới trùng nghĩa**. Tự động phát hiện FFmpeg khi startup, nếu thiếu thì hiển thị `VIDEO_PROCESSOR_NOT_AVAILABLE` và giữ chức năng search metadata.

## 13. Tests / acceptance criteria

Cần test tự động và kiểm thử manual những case:

1. App hiện tại vẫn khởi động và chức năng cũ không regress.
2. Script tiếng Việt phân thành shot có thứ tự, thời lượng và keywords Việt/Anh hợp lệ.
3. Footage nội bộ tìm được theo mô tả nội dung dù tên file không chứa keyword (khi index có dữ liệu phù hợp).
4. Dedupe nguồn trùng URL hoặc provider file ID.
5. Một file video nhiều segment trả đúng các timestamp riêng.
6. Không biết timestamp thì để `null` + `UNVERIFIED`, không bịa thời gian.
7. External provider lỗi/quota hết thì job vẫn có thể trả nội bộ.
8. User không có quyền không xem/download được file Drive nội bộ của user khác.
9. Không download file online khi không rõ quyền sử dụng.
10. Thời lượng video cắt được khớp IN/OUT trong sai số kỹ thuật chấp nhận được; đo bằng ffprobe.
11. CSV/JSON hợp lệ, Unicode tiếng Việt không lỗi, tên file media thứ tự đúng.
12. Export CapCut package mở được các MP4; không yêu cầu import định dạng project không chính thức.
13. Input độc hại trong script/metadata của website không được coi là instruction hệ thống (prompt injection protection).
14. Job chạy lại không tạo duplicate asset/shot nếu request idempotent.
15. Temporary file được dọn dẹp; API có quota / timeout / upload size limit.

## 14. Thứ tự triển khai ưu tiên

**P0 — Có thể sử dụng ngay:**
- Audit repo, tích hợp UI/API theo patterns cũ.
- Script-to-shot plan.
- Search footage nội bộ qua metadata + segments nếu có, kèm link Drive và timestamp có căn cứ.
- Search stock/web qua providers đã cấu hình; nguồn chưa có timestamp phải gắn `UNVERIFIED`.
- Preview/chọn source, lưu selection.
- Export shotlist CSV/JSON.

**P1 — Nâng chất lượng:**
- Incremental Drive sync, thumbnail, FFmpeg indexing, transcript và scene detection.
- Semantic embeddings, reranking.
- Export MP4 media package (khi đủ quyền), SRT nếu có.

**P2 — Tối ưu sau nghiệm thu:**
- Cloud video understanding như TwelveLabs (opt-in, budget/quota/permission).
- Batch index lớn, cost dashboard, cache, monitoring.
- Auto roughcut preview và gợi ý thay thế footage.

## 15. Deliverables từ coding agent

Khi hoàn thành, phải trả lời rõ:

1. **Audit summary**: stack hiện hữu và module tái sử dụng.
2. **Files changed** và lý do thay đổi.
3. **Migrations / env vars** mới (nếu có).
4. **Cách chạy/test** theo repo hiện tại, không dựng app mới.
5. **Những gì hoạt động thực tế** và **những phần còn phụ thuộc API key/Drive permissions/quota**.
6. **Test results**: test nào chạy, pass/fail, lỗi còn tồn tại.
7. **Demo flow**: cách mở màn hình, nhập script, tìm source, xem timestamp, export cho CapCut.

### Tiêu chí thành công cuối cùng

> Người dùng đưa một kịch bản TikTok của The HBG vào ứng dụng hiện tại → AI tự chia shot → tự tìm footage nội bộ + Internet theo khả năng tích hợp được cấu hình → hiển thị nhiều source kèm link/preview/timestamp **có căn cứ** → người dùng chọn nguồn → xuất shotlist và media được phép sử dụng cho CapCut, **mà không ảnh hưởng các tính năng app cũ**.
