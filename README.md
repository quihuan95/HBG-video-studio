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
OPENAI_TTS_MODEL=gpt-4o-mini-tts
VBEE_APP_ID=
VBEE_API_TOKEN=
VBEE_TTS_URL=https://api.vbee.vn/v1/tts
VBEE_WEBHOOK_URL=http://127.0.0.1:8100/api/vbee/callback
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
| `OPENAI_TTS_MODEL` | `gpt-4o-mini-tts` | Model tạo voice cho narration |
| `VBEE_APP_ID` | trống | App ID tạo tại Vbee Studio |
| `VBEE_API_TOKEN` | trống | Bearer token của ứng dụng Vbee |
| `VBEE_TTS_URL` | `https://api.vbee.vn/v1/tts` | Endpoint Vbee Realtime TTS |
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
ID/URL và Google Drive folder chứa Rule. Folder Rule dùng
`BRAND_FACTS.md` và `VIDEO_RULE.md`.
Toàn bộ quy tắc content và sản xuất video nằm trong `VIDEO_RULE.md`;
`CONTENT_RULE.md` và `PRODUCTION_CONFIG.json` không còn được đồng bộ.

Mỗi tab trong Spreadsheet là một video: dòng 1 là tiêu đề, dòng 2 là brief,
dòng 3 là Google Drive folder footage riêng của video, dòng 4 là header và dòng
5 trở đi là các scene/shot. Định dạng cũ không có dòng footage vẫn được hỗ trợ.
Bảng scene gồm 4 cột: `THỜI LƯỢNG` (vd. `0–6s`), `VOICE`, `TEXT TRÊN VIDEO`,
`HÌNH ẢNH / GỢI Ý DỰNG`.
Footage của video được chọn **100% từ Internet** theo kịch bản; không cần folder
footage hay phân loại footage nội bộ. Nút **Tạo video** chỉ yêu cầu một nguồn
Internet đang hoạt động (YouTube qua yt-dlp, hoặc Pexels khi có `PEXELS_API_KEY`).
Production Job có tracker SQLite riêng cho 8 bước: kịch bản, voice, chọn
footage, timeline, branding, phụ đề, render và Drive export. Màn hình **Đang
làm** hiển thị phần trăm, trạng thái từng bước và log, tự cập nhật mỗi 3 giây.
Trang **Lịch sản xuất** hiển thị dạng tháng. Mỗi video/job là một chấm mang màu
của Production Profile; nhiều video trong cùng ngày tạo nhiều chấm. Video chưa
có ngày nằm trong danh sách **Chưa xếp lịch** và có thể gán vào ngày đang chọn.
Production Job chưa kết thúc có nút **Hủy làm video**. Thao tác yêu cầu xác
nhận, chuyển Job/tracker sang `CANCELLED` và ghi audit; Job đang upload Drive
không thể bị hủy giữa chừng.
Job đã hủy nằm trong menu con **Đã hủy**, không nằm ở **Đã hoàn thành**. Video
Topic tương ứng quay lại **Sẽ tạo**; khi tạo lại, hệ thống mở revision mới và
reset tracker nhưng vẫn giữ lịch sử lần chạy đã hủy.
Sidebar **Quản lý video** được tách thành hai menu con: **Tạo video** chỉ chứa
hàng đợi video từ Sheet, còn **Video đã tạo** theo dõi các Job đang làm, hoàn
thành và đã hủy. Không dùng nhiều tab trong cùng một trang.

Production worker chạy nền ngay sau khi tạo Job: tạo voice theo scene; OpenAI
chuyển `VOICE` + `HÌNH ẢNH / GỢI Ý DỰNG` của từng cảnh thành truy vấn tiếng Anh;
tìm clip trên YouTube/Pexels, tải về và cho rea-video tách shot, loại shot có
chữ/quay màn hình/render, chọn đoạn IN/OUT tốt nhất; FFmpeg cắt/scale, ghép
timeline, voice, nhạc, logo và phụ đề; video cuối được duyệt và upload Drive.
Cảnh không có footage Internet dùng được sẽ làm Job thất bại ở bước FOOTAGE
với thông báo rõ cảnh nào.
Job `DRAFT/PROCESSING` được tự tiếp tục sau khi mở lại ứng dụng.

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

Màn hình **AI Footage Search** nhận kịch bản/voice-over, chia thành shot rồi tìm
đồng thời trong thư viện local/Google Drive và stock online. Search nội bộ luôn
hoạt động; Pexels chỉ chuyển sang `READY` khi cấu hình `PEXELS_API_KEY`, nếu
không UI hiển thị `NOT_CONFIGURED`. Timestamp không có bằng chứng luôn được giữ
ở `UNVERIFIED`. Chỉ source nội bộ hoặc stock có quyền tải mới được đưa vào gói
ZIP cho CapCut; các nguồn còn lại chỉ xuất URL trong shotlist CSV/JSON.

Màn hình **Phân tích video tham khảo** dùng REA Video để reverse-engineer một
file local/Drive đã có trong thư viện. Runtime được pin tại commit
`356815c0d61291811551a2b8813b2b571d9b3238` và cài trong virtualenv sidecar,
không cài skill toàn cục hoặc trộn OpenCV với backend:

```powershell
./tools/install_rea_video.ps1
```

Analysis mặc định chạy offline; `REA_VIDEO_ALLOW_VLM=0`. Chỉ bật VLM sau khi
người vận hành cho phép truyền frame/video ra provider và đã cấu hình một env
file riêng qua `REA_VIDEO_ENV_FILE`. Báo cáo REA gốc được tải như attachment,
không nhúng HTML vào origin đặc quyền của Electron. Shot đã duyệt có thể chuyển
thành search brief cho **AI Footage Search**; timestamp reference và timestamp
source thay thế được lưu tách biệt.

Hai tính năng này cũng được nối trực tiếp vào production worker. Sau khi REA
phân tích xong, chọn **Áp dụng vào luồng tạo video** và gắn analysis vào một
Video Topic cùng profile. Ở bước `FOOTAGE`, worker tạo Footage Research Job theo
đúng các scene/voice đã chốt, dùng shot REA làm style brief, tìm toàn bộ kho
local/Drive chung của profile trước rồi mới bổ sung Pexels nếu đã cấu hình.
Source online chỉ được tự dựng khi provider xác nhận quyền tải; research job,
reference analysis và asset đã chọn đều được lưu trong `assets_json` của
production revision để kiểm tra lại.

## API và tài liệu kỹ thuật

Khi backend đang chạy:

- Swagger UI: `http://127.0.0.1:8100/docs`
- Health check: `http://127.0.0.1:8100/health`
- Dashboard WebSocket: `ws://127.0.0.1:8100/ws/dashboard`

Tài liệu trong repository:

- [`.AI/project/ARCHITECTURE.md`](.AI/project/ARCHITECTURE.md): kiến trúc hệ thống
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
