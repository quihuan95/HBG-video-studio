# HBG Video Studio

Ứng dụng desktop dùng AI để phân loại footage từ folder local hoặc Google Drive,
đọc kịch bản, tạo voice, dựng timeline, chèn nhạc/logo/phụ đề và xuất video
trong một giao diện thống nhất.

[![Electron](https://img.shields.io/badge/Electron-desktop-47848F?logo=electron&logoColor=white)](https://www.electronjs.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Python-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## Trạng thái hiện tại

Giai đoạn đầu của bản desktop đã hoàn thành:

- Dashboard React chạy trong cửa sổ Electron.
- Chế độ phát triển có hot reload qua Vite.
- Bản React đã build có thể chạy trực tiếp bằng Electron.
- Electron tự khởi động và dừng FastAPI backend cùng vòng đời ứng dụng.
- Dashboard kết nối FastAPI tại `http://127.0.0.1:8100`.
- WebSocket nhận trạng thái pipeline tại `/ws/dashboard`.
- Dashboard trên trình duyệt vẫn được giữ để phát triển và debug.

Ở giai đoạn hiện tại, Python runtime chưa được đóng gói vào bộ cài. Máy cần có
`.venv` và dependencies Python sau bước cài đặt ban đầu. Google Flow và Chrome
Extension hiện bị tắt và không cần thiết cho workflow footage.

## Kiến trúc

```text
┌──────────────────────────────┐
│ Electron Desktop             │
│ React + TypeScript + Vite    │
└──────────────┬───────────────┘
               │ REST + WebSocket
               ▼
┌──────────────────────────────┐
│ Python Agent                 │
│ FastAPI + Worker + SQLite    │
│ http://127.0.0.1:8100        │
├──────────────┬───────────────┤
│ OpenAI API   │ Google APIs   │
│ Vision/TTS   │ Drive/Sheets  │
└──────────────┴───────────────┘
```

## Yêu cầu hệ thống

- Windows 10/11
- Python 3.10 trở lên; khuyến nghị Python 3.11 hoặc 3.12
- Node.js 20 trở lên
- npm
- FFmpeg và FFprobe trong `PATH`

## Cài đặt backend

Mở PowerShell tại thư mục dự án:

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
./.venv/Scripts/Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt
```

Kiểm tra FFmpeg:

```powershell
ffmpeg -version
ffprobe -version
```

## Cấu hình

Sao chép `.env.example` thành `.env` rồi điền secret. Repository đã có sẵn file
`.env` local và Git sẽ bỏ qua file này:

```dotenv
OPENAI_API_KEY=sk-your-key-here
OPENAI_VISION_MODEL=gpt-6-luna
OPENAI_SCRIPT_MODEL=gpt-6.1-terra
OPENAI_TTS_MODEL=gpt-realtime-2.1-mini
OPENAI_REVIEW_MODEL=gpt-6-luna

GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://127.0.0.1:8100/api/oauth/google/callback
TOKEN_ENCRYPTION_KEY=64-hex-characters

API_HOST=127.0.0.1
API_PORT=8100
FLOWKIT_DEBUG_ENDPOINTS=0
FLOW_ENABLED=0
```

Backend tự động đọc `.env` khi khởi động. Biến môi trường được đặt trực tiếp từ
hệ điều hành vẫn có độ ưu tiên cao hơn giá trị trong file. Sau khi sửa `.env`,
hãy khởi động lại Electron.

Các giá trị OpenAI cũng có thể chỉnh tại **Settings → OpenAI**. API key hiện
tại chỉ được hiển thị dưới dạng trạng thái đã cấu hình; backend không gửi lại
secret cho giao diện. Sau khi lưu, hãy khởi động lại ứng dụng.

### Biến môi trường chính

| Biến | Mặc định | Mô tả |
|---|---:|---|
| `API_HOST` | `127.0.0.1` | Địa chỉ bind FastAPI |
| `API_PORT` | `8100` | Port FastAPI |
| `FLOWKIT_DEBUG_ENDPOINTS` | `0` | Bật các endpoint debug; nên giữ `0` khi vận hành |
| `OPENAI_API_KEY` | trống | API key dùng để phân tích footage và các tác vụ OpenAI |
| `OPENAI_VISION_MODEL` | `gpt-6-luna` | Model tiết kiệm để phân loại frame đại diện của footage |
| `OPENAI_SCRIPT_MODEL` | `gpt-6.1-terra` | Model chia kịch bản, ghép cảnh và lập timeline |
| `OPENAI_TTS_MODEL` | `gpt-realtime-2.1-mini` | Model tạo voice cho narration |
| `OPENAI_REVIEW_MODEL` | `OPENAI_VISION_MODEL` | Model OpenAI xem contact sheet và chấm video |
| `GOOGLE_CLIENT_ID` | trống | OAuth client ID từ Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | trống | OAuth client secret; chỉ backend được đọc |
| `GOOGLE_REDIRECT_URI` | `http://127.0.0.1:8100/api/oauth/google/callback` | Phải trùng chính xác Authorized redirect URI |
| `TOKEN_ENCRYPTION_KEY` | trống | Khóa AES-256, 64 ký tự hex, dùng mã hóa OAuth token trong SQLite |

Các cấu hình nâng cao nằm trong [`agent/config.py`](agent/config.py).

### Kết nối Google Drive và Sheets

Không cần tải credential JSON. Trong Google Cloud Console, tạo OAuth client
loại **Web application**, bật Google Drive API và Google Sheets API, sau đó
thêm Authorized redirect URI chính xác:

```text
http://127.0.0.1:8100/api/oauth/google/callback
```

Authorized JavaScript origins có thể để trống vì authorization code được
xử lý hoàn toàn ở backend. Chép Client ID và Client secret vào `.env`,
rồi tạo khóa mã hóa bằng PowerShell:

```powershell
-join ((1..32 | ForEach-Object { Get-Random -Maximum 256 }) | ForEach-Object { $_.ToString('x2') })
```

Dán chuỗi 64 ký tự nhận được vào `TOKEN_ENCRYPTION_KEY`. Không đổi
khóa này sau khi đã kết nối, vì token cũ sẽ không giải mã được.
Khởi động app, vào **Settings → Google Drive & Sheets → Kết nối
Google**. Trình duyệt hệ thống sẽ mở trang consent; token trả về được
mã hóa AES-256-GCM và lưu trong SQLite, không tạo file token JSON.

## Khởi động ứng dụng

Từ thư mục gốc, chỉ cần một lệnh:

```powershell
npm run dev
```

Lệnh này khởi động Vite, Electron, FastAPI, worker và các service nội bộ
cần cho app. Khi đóng Electron, backend do app khởi tạo cũng được dừng theo.

Lần đầu sau khi clone, nếu dependency frontend chưa được cài:

```powershell
npm run install:dashboard
```

### 1. Khởi chạy toàn bộ ứng dụng

```powershell
npm run dev
```

Electron sẽ tự thực hiện các bước sau:

1. Kiểm tra backend tại `http://127.0.0.1:8100/health`.
2. Dùng backend đang chạy nếu đã có.
3. Nếu chưa có, chạy `.venv/Scripts/python.exe -m agent.main`.
4. Chờ backend sẵn sàng rồi mới mở dashboard.
5. Dừng backend do Electron tạo khi ứng dụng đóng.

Kiểm tra trạng thái nếu cần:

```powershell
Invoke-RestMethod http://127.0.0.1:8100/health
Invoke-RestMethod http://127.0.0.1:8100/api/providers/status
```

Lệnh này chạy Vite và Electron đồng thời. DevTools tự mở trong chế độ phát
triển.

### 2. Chạy từ bản đã build

```powershell
cd dashboard
npm run build
npm run electron:start
```

### Chạy dashboard bằng trình duyệt

```powershell
cd dashboard
npm run web:dev
```

Truy cập `http://127.0.0.1:5173`.

## Production Profile, Video Rule và lịch sản xuất

Vào **Production Profiles** để tạo profile, nhập Google Spreadsheet
ID/URL và Google Drive folder chứa Rule. Folder Rule có thể chứa
`CONTENT_RULE.md`, `BRAND_FACTS.md`, `VIDEO_RULE.md` và
`PRODUCTION_CONFIG.json`.

Mỗi tab trong Spreadsheet là một video: dòng 1 là tiêu đề, dòng 2 là brief,
dòng 3 là Google Drive folder footage riêng của video, dòng 4 là header và dòng
5 trở đi là các scene/shot. Định dạng cũ không có dòng footage vẫn được hỗ trợ.
Nút **Phân loại footage** dùng OpenAI Vision phân tích clip rồi chuyển chúng vào
`_AI_CLASSIFIED/<category>` bên trong folder footage tương ứng. Tiến độ, clip
đang xử lý, category và lỗi được hiển thị theo thời gian thực ngay dưới từng
video; mỗi video chạy độc lập và không khóa thao tác của các video khác.
Kết quả được lưu lâu dài trong database và trong `_AI_CLASSIFIED` dưới dạng
`FOOTAGE_CATALOG.json` (dữ liệu máy đọc) cùng `FOOTAGE_REPORT.md` (báo cáo cho
người vận hành). Giao diện hiện link mở thẳng folder kết quả sau khi hoàn tất.
Production Job chỉ được tạo khi video có folder footage và quá trình phân loại
đạt trạng thái `READY`; `PENDING`, `ANALYZING`, `PARTIAL` và `FAILED` đều bị
chặn ở cả giao diện lẫn API.
Sau khi đạt `READY`, nút **Phân tích lại** cho phép chủ động chạy lại OpenAI và
cập nhật toàn bộ kết quả. Luồng **Tạo video** tái sử dụng kết quả `READY` hiện
có, không phân tích footage lần nữa.
Tiến độ và tối đa 100 dòng log gần nhất được lưu trong SQLite sau từng bước.
Nếu ứng dụng tắt giữa chừng, lần khởi động sau tự khôi phục Job `ANALYZING`;
các clip đã `READY` được giữ lại và luồng thường chỉ xử lý phần còn thiếu.
Production Job cũng có tracker SQLite riêng cho 8 bước: kịch bản, voice, chọn
footage, timeline, branding, phụ đề, render và Drive export. Màn hình **Đang
làm** hiển thị phần trăm, trạng thái từng bước và log, tự cập nhật mỗi 3 giây.

Nhấn **Đồng bộ Rule + Sheet**, sau đó mở **Lịch sản xuất**.
Tab chưa có job có thể tạo Production Job ngay trên lịch. Mỗi job
snapshot Rule version và toàn bộ scene tại thời điểm tạo.

Lịch hiện là lịch sản xuất nội bộ và giữ đúng timezone của Profile.

Khi video đã render xong, duyệt Production Job bằng
`POST /api/production-jobs/{job_id}/approve` với `output_path` trỏ tới file
video local. Ứng dụng tự tạo cây `OUTPUT/DD-MM-YYYY/Tên video/vN`, upload
`final.mp4`, `video.json`, `REVIEW.md` và chuyển job sang
`READY_FOR_MANUAL_UPLOAD`. Nếu Drive lỗi, job giữ `APPROVED` và có thể retry
qua `POST /api/production-jobs/{job_id}/export` hoặc nút **Xuất Drive**.

## Quy trình sản xuất video

```text
1. Nghiên cứu và kiểm chứng nội dung
2. Tạo project và chọn material
3. Tạo nhân vật, bối cảnh và đạo cụ
4. Tạo toàn bộ reference image
5. Tạo ảnh cho từng scene
6. Tạo video từ ảnh scene
7. Review, sửa prompt và regenerate nếu cần
8. Tạo narration/TTS tùy chọn
9. Ghép clip và hậu kỳ bằng FFmpeg
10. Export video và upload vào Google Drive đầu ra
```

Nên gửi các tác vụ tạo media qua batch API để worker tự giới hạn concurrency:

```text
POST /api/requests/batch
GET  /api/requests/batch-status
```

Không nên tự tạo vòng lặp gửi request liên tục vì có thể kích hoạt cơ chế chống
lạm dụng của Google.

## Profile và thư viện footage

Mỗi chủ đề được lưu thành một production profile, gồm rule dựng, logo, voice,
nhạc, Google Sheet kịch bản, các nguồn footage và folder Drive đầu ra. Một
profile có thể dùng đồng thời nhiều folder local và Google Drive.

API nền tảng:

```text
POST   /api/profiles
GET    /api/profiles
PATCH  /api/profiles/{profile_id}
POST   /api/profiles/{profile_id}/footage-sources
GET    /api/profiles/{profile_id}/footage-sources
POST   /api/footage-sources/{source_id}/scan
GET    /api/profiles/{profile_id}/footage
POST   /api/footage/{asset_id}/analyze
```

`footage-sources` nhận `source_type` là `local` hoặc `google_drive`. Với Drive,
`location` có thể là URL folder hoặc folder ID. OpenAI không nhận trực tiếp
video trong Responses API, vì vậy hệ thống dùng FFmpeg lấy tối đa 10 frame đại
diện rồi lưu kết quả phân loại có cấu trúc vào SQLite.

## API và tài liệu kỹ thuật

Khi backend đang chạy:

- Swagger UI: `http://127.0.0.1:8100/docs`
- Health check: `http://127.0.0.1:8100/health`
- Dashboard WebSocket: `ws://127.0.0.1:8100/ws/dashboard`

Tài liệu trong repository:

- [`ARCHITECTURE.md`](ARCHITECTURE.md): kiến trúc hệ thống
- [`dashboard/README.md`](dashboard/README.md): hướng dẫn riêng cho Electron UI
- [`CLAUDE.md`](CLAUDE.md): API và workflow chi tiết
- [`skills/`](skills/): các workflow `/fk-*`
- [`docs/IMAGE_API.md`](docs/IMAGE_API.md): API tạo ảnh

## Cấu trúc thư mục

```text
HBG-Video-Studio/
├── agent/          # FastAPI, worker, providers và SQLite
├── dashboard/      # React UI và Electron main/preload
│   ├── electron/
│   └── src/
├── extension/      # Legacy Flow bridge, hiện không dùng
├── skills/         # Workflow dành cho AI coding agents
├── tools/          # Review board và công cụ hỗ trợ
├── docs/           # Tài liệu kỹ thuật
└── tests/          # Unit/integration tests
```

## Lưu ý an toàn

Giữ `FLOWKIT_DEBUG_ENDPOINTS=0` trong quá trình vận hành bình thường. API local
không có cơ chế đăng nhập và chỉ nên bind vào `127.0.0.1`.

## Lộ trình desktop

- [x] Chạy React dashboard trong Electron
- [x] Hỗ trợ dev mode và compiled renderer
- [x] Kết nối FastAPI và WebSocket local
- [x] Electron tự khởi động/dừng Python backend
- [ ] Lưu cấu hình qua giao diện desktop
- [ ] Đóng gói Python runtime và FFmpeg
- [ ] Tạo bộ cài Windows `.exe`
- [ ] Cập nhật tự động

## Nguồn dự án

HBG Video Studio được phát triển dựa trên
[FlowKit](https://github.com/crisng95/flowkit). Các thay đổi desktop và tài liệu
được duy trì tại:

<https://github.com/quihuan95/HBG-video-studio>

## Giấy phép

Dự án sử dụng giấy phép [MIT](LICENSE).
