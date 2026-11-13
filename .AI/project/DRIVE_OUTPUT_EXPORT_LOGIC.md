# Logic export video ra Google Drive OUTPUT

Tài liệu này mô tả luồng export hiện tại của HBG Video Studio. Mọi khái niệm
Post, caption và image trong tài liệu nguồn cũ đã được chuyển thành Production
Job, video thành phẩm và Production Revision.

## 1. Mục tiêu

Sau khi video được render và duyệt, hệ thống xuất revision hiện tại vào folder
OUTPUT của Production Profile. Khi thành công:

- ghi kết quả vào `production_exports`;
- chuyển Job thành `READY_FOR_MANUAL_UPLOAD`;
- ghi audit event `EXPORT_TO_DRIVE`;
- trả link folder revision trên Google Drive.

## 2. Điểm kích hoạt

- `POST /api/production-jobs/{job_id}/approve`: nhận `output_path`, duyệt Job và
  export ngay. Nếu Drive lỗi, Job vẫn giữ `APPROVED`.
- `POST /api/production-jobs/{job_id}/export`: retry riêng bước Drive, không
  render hoặc duyệt lại.
- UI hiển thị nút **Xuất Drive** cho Job `APPROVED` và link **Mở OUTPUT** sau
  khi export thành công.

## 3. Điều kiện export

1. Production Job và `current_revision_id` còn tồn tại.
2. Job có trạng thái `APPROVED` hoặc `READY_FOR_MANUAL_UPLOAD`.
3. `assets_json.final_video_path` hoặc `assets_json.video_path` trỏ tới file
   video local có thể đọc được.
4. Google OAuth còn hiệu lực và có quyền ghi Drive.
5. Profile có `folder_id_output`/`output_drive_url`; fallback là folder
   `<profile_id>/OUTPUT` trên My Drive.

## 4. Cấu trúc Drive

```text
<folder_id_output>/
└── DD-MM-YYYY/
    └── <video_title>/
        └── v<revision_number>/
            ├── final.mp4
            ├── video.json
            └── REVIEW.md
```

- `/` và `\` trong tiêu đề được đổi thành ` - `.
- Ký tự điều khiển bị loại bỏ, khoảng trắng được chuẩn hóa.
- Tên video tối đa 120 ký tự.
- Folder/file cùng tên trong đúng parent được tái sử dụng khi retry.

## 5. Nội dung output

### `final.mp4`

Video thành phẩm của revision hiện tại. Phần mở rộng và MIME được giữ theo file
nguồn nếu output không phải MP4.

### `video.json`

Manifest gồm Job, Revision, Profile, Video Topic, lịch sản xuất, Rule version,
Rule hash, Revision hash, SHA-256 và dung lượng video, thời gian export và toàn
bộ Drive file/folder ID.

### `REVIEW.md`

Biên bản vận hành gồm Profile, tên video, ngày sản xuất, revision, trạng thái và
danh sách file trong bộ output.

## 6. Idempotency và chống xung đột

- Upload tìm theo `parent + file name`: có thì PATCH nội dung và giữ file ID,
  chưa có thì tạo mới.
- `_active_exports` ngăn hai lượt export cùng Job trong một process; lượt sau
  nhận `EXPORT_IN_PROGRESS`.
- Sau upload, transaction `BEGIN IMMEDIATE` kiểm tra lại
  `current_revision_id`. Nếu revision đổi, trả `EXPORT_REVISION_CONFLICT` và
  không ghi trạng thái export local.
- Record cũ của cùng `job_id + revision_id` được thay thế trong transaction,
  nên retry không tạo bản ghi trùng.

## 7. Trình tự xử lý

```text
Nhận job_id
  → khóa export theo Job
  → kiểm tra Job, revision, trạng thái và video local
  → resolve OUTPUT
  → tạo/tái sử dụng folder ngày, video, revision
  → upload final video
  → upload video.json và REVIEW.md
  → kiểm tra revision trong transaction SQLite
  → ghi production_exports + cập nhật Job + ghi audit
  → trả Drive folder URL
```

## 8. API thành công

```json
{
  "success": true,
  "driveFolderId": "revision-folder-id",
  "driveFolderUrl": "https://drive.google.com/drive/folders/revision-folder-id",
  "files": {
    "video": "video-file-id",
    "manifest": "manifest-file-id",
    "review": "review-file-id"
  }
}
```

## 9. Xử lý lỗi

- `VIDEO_FILE_MISSING`: chưa có file render hợp lệ.
- `JOB_NOT_APPROVED`: Job chưa được duyệt.
- `OUTPUT_FOLDER_MISSING`: Profile chưa cấu hình OUTPUT và fallback không có.
- `EXPORT_IN_PROGRESS`: Job đang được export.
- `EXPORT_REVISION_CONFLICT`: revision đổi trong lúc upload.
- Lỗi OAuth/quyền/upload trả lỗi Drive; Job đã duyệt vẫn ở `APPROVED` để retry.

Google Drive và SQLite không nằm trong cùng transaction. File đã upload trước
một lỗi local có thể còn trên Drive; lần retry sẽ reconcile bằng cách cập nhật
file cùng tên.

## 10. File code liên quan

- `agent/services/drive_output_export.py`: Drive adapter và điều phối export.
- `agent/api/content_calendar.py`: endpoint approve/export/lịch sử export.
- `agent/db/schema.py`: `production_exports`, `production_audit_events`.
- `dashboard/src/pages/PostManagementPage.tsx`: nút retry và link OUTPUT.
