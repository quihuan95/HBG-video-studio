# Logic Profile → Rule → Tạo bài → Ghi trên lịch

Tài liệu này mô tả luồng đang được triển khai trong HBG Content Studio Phase 1, từ lúc cấu hình một Content Profile, đồng bộ Rule và kế hoạch nội dung, tạo bài, cho đến khi bài xuất hiện trên Lịch nội dung và được đăng theo lịch.

## 1. Sơ đồ tổng thể

```text
Content Profile
  ├─ cấu hình thương hiệu, timezone, giờ mặc định, workflow
  ├─ trỏ tới thư mục RULES trên Google Drive
  └─ trỏ tới Google Sheet CONTENT_PLAN
             │
             ├───────────────┐
             ▼               ▼
     Đồng bộ Rule       Đồng bộ tab TOPICS
     tạo Rule version   tạo/cập nhật Topic
             │               │
             └───────┬───────┘
                     ▼
              Chọn topic để tạo bài
                     ▼
       Caption → ảnh → revision → kiểm tra
                     ▼
          semi_auto          auto/manual
          NEEDS_REVIEW       APPROVED/export
                     │
                     ▼
                Lịch nội dung
       ngày = content_date, giờ = scheduled_time
                     ▼
       Đến hạn → đăng Facebook nếu đủ trạng thái
```

## 2. Profile là cấu hình gốc

Mỗi Profile đại diện cho một thương hiệu/kênh nội dung. Profile là khóa liên kết của Rule, Topic và Post qua `profile_id`.

Các trường ảnh hưởng trực tiếp đến luồng:

| Trường | Vai trò |
|---|---|
| `name`, `brand`, `type`, `language` | Ngữ cảnh thương hiệu dùng khi sinh nội dung |
| `timezone` | Múi giờ dùng để xác định bài đã đến giờ đăng; mặc định `Asia/Ho_Chi_Minh` |
| `time` | Giờ đăng mặc định nếu topic không có `publish_time`; mặc định `09:00` |
| `folder_id_rules` | Thư mục Drive chứa các file Rule |
| `folder_id_output` | Thư mục xuất bài; đồng thời có thể suy ra thư mục `RULES` nếu chưa cấu hình `folder_id_rules` |
| `sheet_id_topics` | Google Sheet chứa tab `TOPICS`/kế hoạch nội dung |
| `workflow_mode` | `manual`, `semi_auto` hoặc `auto` |
| `active` | Chỉ Profile đang hoạt động mới được automation xử lý |
| `color` | Màu nhận diện Profile trên Lịch nội dung |
| `logo_data` | Logo được ghép lên ảnh AI |
| `facebook_page_id` | Page ID hoặc link Facebook dùng khi tự động đăng |
| `retain_removed_posts` | Khi topic bị xóa khỏi Sheet: lưu post thành `ARCHIVED` hay xóa post |

Điều kiện nền để chạy đầy đủ automation:

1. Profile tồn tại và `active = 1`.
2. Có nguồn Rule hợp lệ.
3. Có `sheet_id_topics` và kết nối Google.
4. Tab `TOPICS` có đủ dữ liệu lịch.

## 3. Từ Profile đến Rule

### 3.1 Nguồn Rule

Hệ thống tìm thư mục theo thứ tự:

1. `profile.folder_id_rules`.
2. Nếu trống, thay hậu tố `/OUTPUT` trong `folder_id_output` thành `/RULES`.

Trong thư mục này, hệ thống đọc tối đa ba file Markdown theo đúng tên:

- `CONTENT_RULE.md`
- `BRAND_FACTS.md`
- `IMAGE_RULE.md`

Nội dung các file hiện có được ghép theo thứ tự trên, phân cách bằng `---`. File tùy chọn `PUBLISH_CONFIG.json` được đọc vào `publish_config_json`; JSON lỗi không làm dừng việc đồng bộ Rule.

### 3.2 Version và snapshot

- Nếu nội dung ghép giống Rule published mới nhất: không tạo version mới.
- Nếu nội dung thay đổi: tạo `rule_versions.version + 1`, trạng thái `published` và hash mới.
- Có thể tạo Rule trực tiếp qua API mà không cần Drive.
- Khi tạo Post revision đầu tiên, hệ thống chụp `rule_version_id` và `rule_hash` vào revision.

Vì vậy, Rule mới chỉ áp dụng cho lần sinh nội dung sau. Revision cũ vẫn truy vết được Rule đã dùng tại thời điểm tạo.

## 4. Từ Profile đến kế hoạch trên Sheet

Hệ thống đọc vùng `TOPICS!A1:Z500` trong Google Sheet.

### 4.1 Cột bắt buộc

| Cột | Định dạng | Ý nghĩa |
|---|---|---|
| `topic_id` | Chuỗi, duy nhất trong Profile | Khóa nghiệp vụ liên kết Topic với Post |
| `content_date` | `YYYY-MM-DD` hoặc `DD/MM/YYYY` | Ngày bài nằm trên lịch |
| `publish_time` | `HH:mm` hoặc `HH:mm:ss` | Giờ dự kiến đăng |
| `topic_title` | Chuỗi không rỗng | Chủ đề dùng để sinh bài |

Cột tùy chọn đang được sử dụng: `image_rule`, `source_image_drive_link`, `image_frame_drive_link` (có hỗ trợ một số tên tiếng Việt tương đương cho hai cột link).

### 4.2 Quy tắc đồng bộ

- Dòng trống được bỏ qua.
- Thiếu header, thiếu giá trị bắt buộc, ngày/giờ sai hoặc trùng `topic_id` làm lần sync thất bại.
- Topic mới được insert với `status = READY`, `source_revision = 1`.
- Topic thay đổi được cập nhật, tăng `source_revision` và ghi `source_hash` mới.
- Topic không còn trên Sheet sẽ bị xóa khỏi bảng `topics`.
- Post liên kết với topic bị gỡ khỏi Sheet được chuyển `ARCHIVED` nếu `retain_removed_posts = 1`; nếu không, post bị xóa.

Mỗi dòng Topic hợp lệ chính là một ô lịch nguồn, kể cả khi chưa tạo Post.

## 5. Tạo bài từ Topic

Có hai điểm vào chính:

- Thủ công: `POST /api/posts` hoặc chọn một Topic trên giao diện.
- Automation: chọn các Topic rồi gọi `POST /api/automation/run`.

Trước khi tạo Post, hệ thống bắt buộc Profile phải tồn tại và có Rule published mới nhất.

### 5.1 Chốt ngày và giờ

Automation tính lịch theo ưu tiên:

```text
content_date   = scheduleOverride.date  || topic.content_date
scheduled_time = scheduleOverride.time  || topic.publish_time || profile.time || "09:00"
```

Khi gọi API tạo Post trực tiếp, `date` và `time` được truyền vào `createPostFromTopic`; nếu thiếu ngày thì dùng ngày hiện tại, nếu thiếu giờ thì mặc định `09:00`.

### 5.2 Post và revision đầu tiên

Hệ thống tạo:

- Một dòng `posts` với `status = DRAFT`.
- Một `post_revisions` số 1.
- Snapshot gồm `topic_id`, `topic_title`, `content_date`, `scheduled_time`.
- Snapshot Rule gồm `rule_version_id` và `rule_hash`.
- Hai blocker ban đầu: caption chưa có nội dung và chưa có ảnh.

Post liên kết với Topic bằng cặp `profile_id + topic_id`. `creation_source` là `manual` hoặc `automation`.

### 5.3 Sinh nội dung

Luồng automation của một Topic:

1. Lấy Rule published mới nhất.
2. Sinh caption, headline, CTA và image brief bằng AI.
3. Tạo revision mới, đổi post tạm thời sang `GENERATING`.
4. Nếu có ảnh nguồn Drive, tạo ảnh theo từng ảnh nguồn; nếu không, lập danh sách image brief rồi tạo ảnh mới.
5. Ghép logo Profile và khung ảnh Drive nếu có.
6. Tạo revision mới chứa bộ ảnh.
7. Kiểm tra lại hai blocker: caption không rỗng và có ảnh.

Mỗi lần sửa nội dung tạo một revision mới và đưa Post về `NEEDS_REVIEW`; approval cũ không còn đại diện cho revision mới.

### 5.4 Chống tạo trùng và ghi đè

Nếu đã có Post cho `profile_id + topic_id`:

- `READY_FOR_MANUAL_UPLOAD` hoặc `MANUALLY_UPLOADED`: bỏ qua.
- `NEEDS_REVIEW` trong `semi_auto`: giữ nguyên để chờ duyệt.
- `APPROVED`: chỉ thử lại bước export Drive, không sinh lại nội dung.
- Post do người dùng tạo (`creation_source = manual`) không bị scheduled automation sinh lại caption/ảnh.

## 6. Nhánh workflow sau khi tạo bài

### `semi_auto`

Sau khi có caption và ảnh, Post chuyển sang `NEEDS_REVIEW`. Người dùng duyệt hoặc yêu cầu sửa.

Điều kiện duyệt:

- Caption không rỗng.
- Có ảnh hoàn chỉnh.

Duyệt thành công tạo bản ghi approval gắn với chính `revision_id` và `revision_hash`, sau đó Post chuyển `APPROVED`.

### `auto` và luồng automation không phải `semi_auto`

Hệ thống tự duyệt, chuyển `APPROVED` và export bài lên Google Drive. Export thất bại không làm sinh lại caption/ảnh ở lần chạy tiếp theo; hệ thống chỉ retry export.

### `manual`

Không được cron chọn để tự sinh nội dung, nhưng người dùng vẫn có thể chọn Topic và chạy luồng tạo bài thủ công. Bài do người dùng tạo được bảo vệ khỏi việc scheduled automation ghi đè.

## 7. Logic ghi và hiển thị trên Lịch nội dung

Lịch không có bảng riêng. Giao diện tổng hợp dữ liệu từ:

1. `GET /api/topics?all=true`: các lịch nguồn từ Sheet.
2. `GET /api/posts`: các bài đã được tạo.

Quy tắc hiển thị:

- Topic chưa có Post: hiển thị theo `topic.content_date` và `topic.publish_time`; bấm vào có thể tạo bài.
- Topic đã có Post: hiển thị Post theo `post.content_date` và `post.scheduled_time`; Topic nguồn tương ứng không hiển thị thêm lần nữa.
- Post không gắn Topic vẫn hiển thị độc lập trên lịch.
- Màu chấm lịch lấy từ `profile.color`.
- Bấm một Post trên lịch mở Studio; bấm một Topic chưa có Post mở thao tác tạo bài.
- Mục không có ngày hợp lệ được đưa vào nhóm “Lịch chưa có ngày”.

Tóm lại, “ghi trên lịch” xảy ra ở hai thời điểm:

```text
Sync Sheet thành công → Topic xuất hiện trên lịch ở trạng thái chưa có bài
Tạo Post thành công   → Post thay Topic trên cùng slot ngày/giờ
```

Ngày/giờ gốc được lưu dưới dạng local schedule (`content_date`, `scheduled_time`). Các event/audit timestamp khác được lưu ISO/UTC.

## 8. Đăng bài khi đến lịch

Scheduled automation xét từng Profile theo `profile.timezone`, rồi lấy các Post thỏa tất cả điều kiện:

- Profile đang hoạt động và workflow là `semi_auto` hoặc `auto`.
- Post có trạng thái `APPROVED` hoặc `READY_FOR_MANUAL_UPLOAD`.
- Topic liên kết vẫn tồn tại, hoặc Post không gắn Topic.
- `content_date` đã qua, hoặc đúng ngày và `scheduled_time <= giờ hiện tại`.

Các Post được xử lý theo `content_date`, `scheduled_time`, `created_at`. Hệ thống đăng qua Meta Graph API, sau đó ghi nhận URL bài đăng và chuyển trạng thái bằng luồng `markManuallyUploaded` thành `MANUALLY_UPLOADED`.

Lưu ý: lịch trong ứng dụng là lịch nội bộ. Hệ thống không tạo scheduled post trước trên Facebook; đến giờ, cron mới gọi Meta Graph API để đăng ngay.

## 9. State flow chính

```text
DRAFT
  └─ bắt đầu AI ───────────────► GENERATING
                                   │
                         ┌─────────┴─────────┐
                         ▼                   ▼
                    NEEDS_REVIEW          lỗi → DRAFT
                         │
                 duyệt   │  yêu cầu sửa
                         ▼       └──────────► DRAFT
                     APPROVED
                         │
                  export/chuẩn bị đăng
                         ▼
              READY_FOR_MANUAL_UPLOAD
                         │
                đăng tay hoặc tự động
                         ▼
                MANUALLY_UPLOADED

Topic bị gỡ khỏi Sheet và được giữ lại → ARCHIVED
```

## 10. API liên quan

| API | Mục đích |
|---|---|
| `POST /api/profiles` | Tạo Profile |
| `PATCH /api/profiles/:id` | Cập nhật Profile |
| `GET/POST /api/profiles/:id/rules` | Xem hoặc tạo Rule version |
| `POST /api/profiles/:id/sync-sheet` | Đồng bộ Rule Drive và Topic Sheet cho một Profile |
| `POST /api/profiles/sync-all` | Đồng bộ mọi Profile phù hợp |
| `GET /api/topics?all=true` | Lấy nguồn lịch Topic |
| `POST /api/automation/run` | Tạo bài từ danh sách Topic, có thể kèm override lịch |
| `GET /api/automation/jobs/:id` | Theo dõi tiến độ job tạo bài |
| `POST /api/automation/jobs/:id/cancel` | Yêu cầu hủy job |
| `POST /api/posts` | Tạo Post thủ công |
| `GET /api/posts` | Lấy các Post để hiển thị/ghép lịch |

## 11. Ví dụ end-to-end

Giả sử Profile `HBG` có timezone `Asia/Ho_Chi_Minh`, workflow `semi_auto`, màu xanh và giờ mặc định `09:00`.

Sheet có dòng:

```text
topic_id:       T001
content_date:   2026-11-12
publish_time:   19:30
topic_title:    5 cách tối ưu nội dung Fanpage
```

Kết quả:

1. Sync tạo Topic `T001`; lịch ngày 12/11 hiển thị một chấm màu của Profile HBG lúc 19:30.
2. Người dùng chọn Topic và chạy tạo bài.
3. Hệ thống dùng Rule version mới nhất để sinh caption và ảnh; Post nhận `content_date = 2026-11-12`, `scheduled_time = 19:30`.
4. Vì workflow là `semi_auto`, Post dừng ở `NEEDS_REVIEW`.
5. Trên lịch, Post thay cho Topic nguồn; bấm vào sẽ mở Studio.
6. Sau khi duyệt, Post thành `APPROVED`.
7. Khi giờ địa phương của Profile đạt 19:30 ngày 12/11/2026, scheduled automation đăng bài lên Facebook và ghi nhận URL/trạng thái đã đăng.

## 12. Các nguyên tắc cần giữ khi sửa code

- Luôn dùng `profile_id + topic_id` để nhận diện một slot nội dung, không dùng vị trí dòng Sheet.
- Không hiển thị đồng thời Topic và Post của cùng một slot trên lịch.
- Không cập nhật nội dung trực tiếp lên revision cũ; luôn tạo revision mới.
- Approval phải gắn với revision/hash cụ thể.
- Rule phải được snapshot vào revision để bảo đảm truy vết.
- Scheduled automation không được ghi đè Post do người dùng tạo.
- So sánh giờ đến hạn theo timezone của Profile, không theo timezone máy chủ.
- Topic thiếu ngày/giờ không được automation tạo bài.
