# Logic Profile → Video Rule → Kịch bản → Production Job → Lịch sản xuất

Tài liệu này mô tả đúng domain của HBG Video Studio: tạo video từ kịch bản,
footage, voice, text, nhạc và logo; export file hoàn chỉnh rồi tải lên Google
Drive. Đầu ra cuối cùng là file video hoàn chỉnh trong Google Drive.

## 1. Sơ đồ tổng thể

```text
Production Profile
  ├─ thương hiệu, logo, giọng đọc, ngôn ngữ, timezone
  ├─ trỏ tới folder VIDEO_RULES trên Google Drive
  ├─ trỏ tới folder footage local/Drive
  ├─ trỏ tới Spreadsheet kịch bản (mỗi tab là một video)
  └─ trỏ tới folder Drive đầu ra
                │
        ┌───────┴────────┐
        ▼                ▼
  Đồng bộ Rule      Đồng bộ từng tab video
  tạo Rule version  tạo/cập nhật Video Topic
        └───────┬────────┘
                ▼
       Tạo Production Job
                ▼
   phân tích kịch bản → tạo voice → lập timeline
                ▼
   chọn/cắt footage → nhạc → logo → subtitle
                ▼
       review → render → export Drive
                ▼
         Lịch sản xuất nội bộ
```

## 2. Production Profile là cấu hình gốc

Mỗi Profile đại diện cho một thương hiệu hoặc một kênh video. Profile là khóa
liên kết của Rule, Video Topic, footage và Production Job qua `profile_id`.

| Trường | Vai trò |
|---|---|
| `name`, `brand`, `language`, `tone` | Ngữ cảnh thương hiệu và ngôn ngữ video |
| `timezone` | Múi giờ của lịch sản xuất; mặc định `Asia/Ho_Chi_Minh` |
| `default_time` | Giờ bắt đầu xử lý mặc định; mặc định `09:00` |
| `folder_id_rules` | Folder Drive chứa bộ Video Rule |
| `sheet_id_topics` | Spreadsheet kịch bản; mỗi tab là một video |
| `footage_sources` | Các folder footage local hoặc Google Drive |
| `output_drive_url` | Folder Drive nhận video đã export |
| `workflow_mode` | `manual`, `semi_auto` hoặc `auto` |
| `logo_path`, `logo_position` | Logo và vị trí chèn vào video |
| `voice_provider`, `voice_id` | Cấu hình giọng đọc |
| `music_path` | Nhạc nền mặc định, nếu có |
| `active`, `color` | Trạng thái automation và màu trên lịch |
| `retain_removed_jobs` | Giữ job thành `ARCHIVED` khi dòng Sheet bị xóa |

Điều kiện để chạy production đầy đủ:

1. Profile tồn tại và đang hoạt động.
2. Có Video Rule published.
3. Có kịch bản hợp lệ từ Sheet hoặc người dùng nhập trực tiếp.
4. Có ít nhất một footage source đã scan.
5. OpenAI và Google đã được cấu hình nếu workflow sử dụng chúng.

## 3. Bộ Video Rule

### 3.1 Các file trong folder Rule

Hệ thống đọc tối đa bốn file theo đúng tên:

- `CONTENT_RULE.md`: mục tiêu, đối tượng, giọng điệu và nguyên tắc kịch bản.
- `BRAND_FACTS.md`: dữ kiện thương hiệu được phép sử dụng.
- `VIDEO_RULE.md`: quy tắc dựng, footage, voice, subtitle, logo, nhạc và export.
- `PRODUCTION_CONFIG.json`: cấu hình máy đọc được; file tùy chọn.

Nội dung ba file Markdown được ghép theo thứ tự trên, phân cách bằng `---`.

### 3.2 Version và snapshot

- Nếu nội dung và production config không đổi: không tạo version mới.
- Nếu thay đổi: tạo `rule_versions.version + 1` với hash mới.
- Có thể tạo Rule trực tiếp qua API mà không cần Drive.
- Khi tạo Production Job, revision đầu tiên snapshot `rule_version_id` và
  `rule_hash`.
- Job cũ luôn truy vết được bộ Rule đã dùng, kể cả khi Rule mới được cập nhật.

## 4. Kế hoạch video trên Google Sheet

Một Google Spreadsheet chứa nhiều video. **Mỗi tab (sheet) là một video độc
lập**; không có tab tổng `VIDEOS` và không dùng mỗi dòng làm một video.

Hệ thống đọc metadata của spreadsheet trước để lấy toàn bộ tab cùng `sheetId`.
`sheetId` (giá trị `gid` trong URL) là khóa nguồn ổn định của video. Tên tab là
tên hiển thị và có thể đổi mà không tạo video mới.

Ví dụ URL:

```text
https://docs.google.com/spreadsheets/d/<spreadsheet_id>/edit?gid=379799720
```

Khóa video nguồn:

```text
profile_id + spreadsheet_id + sheet_id
```

### 4.1 Cấu trúc cố định của mỗi tab

| Vùng | Nội dung |
|---|---|
| Dòng 1 | Tiêu đề video; có thể merge nhiều cột |
| Dòng 2 | Brief tổng: format, mục tiêu, hook, giọng điệu, logo/hotline |
| Dòng 3 | Header của bảng scene |
| Dòng 4 trở đi | Mỗi dòng là một scene/shot theo thứ tự timeline |

Các cột bắt buộc ở dòng 3:

| Cột | Header | Ý nghĩa |
|---|---|---|
| A | `Phần` | Tên phân đoạn: Hook, nội dung, Compare, Montage, End... |
| B | `Shot` | Mã shot; chấp nhận `OF`, `01`, `02`, `EF`... |
| C | `Timecode` | Khoảng thời gian như `00:03–00:09` |
| D | `Hình ảnh đề xuất` | Mô tả footage cần xuất hiện |
| E | `Text on screen` | Chữ hiển thị trên video |
| F | `Voice-over (VI) – lời đọc tiếng Việt` | Nội dung dùng để tạo voice |
| G | `Cách dựng` | Nhịp cắt, transition, bố cục và chỉ dẫn dựng |
| H | `Tư liệu tham khảo` | Keyword hoặc link dùng để match footage |
| I | `Âm thanh` | Chỉ dẫn nhạc, beat, ambience và sound effect |
| J | `Ghi chú` | Logo, hotline và yêu cầu bổ sung |

Header được normalize khoảng trắng, chữ hoa/thường và một số tên viết tắt,
nhưng không suy đoán khi thiếu một cột bắt buộc.

### 4.2 Chuẩn hóa một tab thành Video Topic

Metadata video lấy từ tab:

```text
source_sheet_id = sheetId/gid
source_tab_name = tên tab
title           = nội dung dòng 1, fallback sang tên tab
brief           = nội dung dòng 2
orientation     = suy ra từ brief (ví dụ "Format 9:16"), fallback Profile
target_duration = end timecode lớn nhất
script_hash     = hash của title + brief + toàn bộ scene đã normalize
```

Mỗi dòng scene được chuẩn hóa thành:

```text
scene_order
section
shot_code
start_time_s
end_time_s
duration_s
visual_intent
on_screen_text
narration_text
editing_instruction
footage_references
audio_instruction
notes
```

Timecode chấp nhận dấu `-`, `–` hoặc `—`. Các khoảng phải hợp lệ, không âm và
không chồng lấn sai thứ tự. Dòng hoàn toàn trống được bỏ qua.

### 4.3 Quy tắc đồng bộ

- Tab mới tạo Video Topic `READY`, `source_revision = 1`.
- Tab đổi tên nhưng giữ cùng `sheetId`: cập nhật Topic hiện có.
- Nội dung title, brief hoặc scene thay đổi: tăng `source_revision` và cập nhật
  `source_hash`.
- Nội dung không đổi: không tạo revision mới.
- Tab ẩn được đồng bộ thành `ARCHIVED` và không được automation chọn; khi hiện
  lại, Topic quay về `READY`.
- Tab bị xóa: Topic bị xóa; Production Job đã tồn tại được giữ `ARCHIVED` để
  bảo toàn lịch sử và asset render.
- Thứ tự tab không phải khóa và không ảnh hưởng nhận diện video.
- Sync một URL có `gid` có thể ưu tiên tab đó trên UI, nhưng sync Profile vẫn
  đọc toàn bộ tab trong spreadsheet.

Lịch sản xuất không lấy từ từng tab vì mẫu sheet không chứa ngày/giờ. Topic mới
được đưa vào nhóm **Sẽ tạo / Chưa xếp lịch**. Người dùng đặt
`production_date` và `scheduled_time` trong ứng dụng; automation chỉ chạy sau
khi hai giá trị này đã được chốt.

## 5. Tạo Production Job

Điểm vào:

- Thủ công: chọn Video Topic trong Quản lý video.
- Nhập trực tiếp: tạo Job với title, script, ngày và giờ.
- Automation: chọn các Topic đến lịch của Profile `semi_auto` hoặc `auto`.

Trước khi tạo Job, Profile phải có Rule published và kịch bản không rỗng.

### 5.1 Chốt lịch

```text
production_date = override.date || topic.production_date || ngày người dùng chọn
scheduled_time  = override.time || topic.scheduled_time || profile.default_time || "09:00"
```

Đây là lịch bắt đầu sản xuất video.

### 5.2 Revision đầu tiên

Hệ thống tạo:

- Một `production_jobs` trạng thái `DRAFT`.
- Một `production_revisions` số 1.
- Snapshot title, script, lịch, orientation và target duration.
- Snapshot `rule_version_id` và `rule_hash`.
- Blocker ban đầu: kịch bản rỗng, chưa có voice, timeline, footage hoặc render.

Nếu đã có Job cho `profile_id + spreadsheet_id + source_sheet_id`, hệ thống trả Job hiện có và không
tạo trùng.

## 6. Pipeline sản xuất video

### Giai đoạn 1 — Phân tích kịch bản

OpenAI chuẩn hóa kịch bản thành danh sách scene:

- `scene_order`
- `narration_text`
- `duration_s`
- `visual_intent`
- `footage_queries`
- `on_screen_text`
- `transition_hint`

Tổng thời lượng scene phải bám sát `target_duration_s` nếu được cấu hình.

### Giai đoạn 2 — Voice

- Tạo voice từ `narration_text` theo thứ tự scene.
- Đo thời lượng audio thật sau khi tạo.
- Timeline được điều chỉnh theo voice; không cắt mất câu.
- Lưu voice asset và metadata vào revision mới.

### Giai đoạn 3 — Chọn và cắt footage

- Chỉ chọn footage đã được AI phân tích và trạng thái `READY`.
- Match theo tag, summary, subject, action, location và usable ranges.
- Không dùng cùng một đoạn footage lặp lại sát nhau nếu còn lựa chọn khác.
- Nếu thiếu footage phù hợp, Job chuyển `NEEDS_INPUT` và chỉ rõ scene thiếu.

### Giai đoạn 4 — Hậu kỳ

- Cắt footage theo timeline voice.
- Chèn nhạc với âm lượng theo Rule; voice luôn được ưu tiên.
- Chèn logo theo Profile và safe zone.
- Tạo subtitle từ narration/voice timing, tối đa hai dòng.
- Chèn on-screen text nếu scene yêu cầu.
- Render preview trước khi export bản cuối.

### Giai đoạn 5 — Review và export

- OpenAI review contact sheet hoặc frame đại diện của preview.
- Kiểm tra khớp kịch bản, subtitle, logo, khung hình và lỗi hình ảnh.
- `semi_auto`: chuyển `NEEDS_REVIEW`, người dùng duyệt rồi mới export.
- `auto`: tự duyệt khi không có blocker nghiêm trọng.
- Export MP4 và upload vào `output_drive_url`.
- Lưu `output_drive_file_id`, URL, checksum, duration và thông số render.

## 7. Trạng thái Production Job

```text
DRAFT
  └─ bắt đầu ───────────────► ANALYZING_SCRIPT
                                 ▼
                           GENERATING_VOICE
                                 ▼
                           MATCHING_FOOTAGE
                                 ▼
                              EDITING
                                 ▼
                             RENDERING
                                 ▼
                  ┌──────────────┴──────────────┐
                  ▼                             ▼
             NEEDS_REVIEW                 NEEDS_INPUT
                  │                             │
               duyệt                        bổ sung
                  ▼                             └──► tiếp tục stage bị dừng
              APPROVED
                  ▼
              EXPORTING
                  ▼
              COMPLETED

Lỗi có thể phục hồi → FAILED, lưu stage và error để retry đúng bước.
Topic bị xóa nhưng giữ lịch sử → ARCHIVED.
```

## 8. Lịch sản xuất

Lịch tổng hợp từ Video Topic và Production Job:

1. Topic chưa có Job: hiển thị theo `production_date/scheduled_time`, cho phép
   bấm để tạo video.
2. Topic đã có Job: chỉ hiển thị Job; không hiển thị Topic lần thứ hai.
3. Job nhập trực tiếp không gắn Topic vẫn hiển thị độc lập.
4. Màu lấy từ Profile.
5. Bấm Job mở màn hình chi tiết pipeline, asset, blocker và preview.
6. Mục không có ngày hợp lệ nằm trong nhóm “Chưa xếp lịch”.

Ba nhóm quản lý chính:

- **Sẽ tạo**: Video Topic chưa có Production Job.
- **Đang làm**: Job từ `DRAFT` đến `EXPORTING`, gồm cả `NEEDS_INPUT` và
  `NEEDS_REVIEW`.
- **Đã hoàn thành**: `COMPLETED` hoặc `ARCHIVED`.

## 9. Automation theo timezone

Scheduler xét từng Profile theo `profile.timezone` và chỉ chạy khi:

- Profile `active = 1`.
- Workflow là `semi_auto` hoặc `auto`.
- Topic có kịch bản và lịch hợp lệ.
- Đã đến `production_date + production_time`.
- Chưa có Job cho `profile_id + spreadsheet_id + source_sheet_id`.

Job manual không bị automation ghi đè. Retry phải tiếp tục từ stage lỗi gần
nhất thay vì tạo lại voice, footage hoặc render đã thành công.

## 10. API mục tiêu

| API | Mục đích |
|---|---|
| `POST /api/profiles` | Tạo Production Profile |
| `PATCH /api/profiles/:id` | Cập nhật Profile |
| `GET/POST /api/profiles/:id/rules` | Xem hoặc tạo Video Rule version |
| `POST /api/profiles/:id/sync-sheet` | Đồng bộ Rule Drive và Sheet video |
| `POST /api/profiles/sync-all` | Đồng bộ mọi Profile hoạt động |
| `GET /api/video-topics?all=true` | Lấy nguồn lịch video |
| `POST /api/production-jobs` | Tạo Job thủ công hoặc từ Topic |
| `GET /api/production-jobs` | Lấy danh sách Job |
| `GET /api/production-jobs/:id` | Chi tiết pipeline và revision hiện tại |
| `POST /api/production-jobs/:id/run` | Chạy/tiếp tục pipeline |
| `POST /api/production-jobs/:id/retry` | Retry stage lỗi |
| `POST /api/production-jobs/:id/approve` | Duyệt revision hiện tại |
| `GET /api/production-calendar` | Hợp nhất Topic và Job trên lịch |

## 11. Nguyên tắc bắt buộc

- Luôn dùng `profile_id + spreadsheet_id + source_sheet_id` để nhận diện
  video nguồn; không dùng tên hay vị trí tab làm khóa.
- Không hiển thị đồng thời Topic và Job của cùng slot trên lịch.
- Không sửa trực tiếp revision cũ; mỗi lần thay kịch bản/timeline/asset tạo
  revision mới.
- Approval gắn với revision ID và hash cụ thể.
- Rule version được snapshot vào revision.
- Automation không ghi đè Job manual.
- So sánh lịch theo timezone Profile, không theo timezone máy chủ.
- Không đánh dấu `COMPLETED` trước khi file render tồn tại, kiểm tra được và đã
  upload Drive thành công.
- Đầu ra cuối cùng là file video trên Google Drive.
