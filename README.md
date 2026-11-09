# HBG Video Studio

Ứng dụng desktop hỗ trợ xây dựng và vận hành quy trình sản xuất video AI từ
Google Flow: quản lý dự án, nhân vật, bối cảnh, ảnh tham chiếu, scene, video,
thuyết minh và hậu kỳ trong một giao diện thống nhất.

[![Electron](https://img.shields.io/badge/Electron-desktop-47848F?logo=electron&logoColor=white)](https://www.electronjs.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Python-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Chrome](https://img.shields.io/badge/Chrome-MV3-4285F4?logo=googlechrome&logoColor=white)](https://developer.chrome.com/docs/extensions/)
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
`.venv` và dependencies Python sau bước cài đặt ban đầu. Chrome Extension vẫn
cần được cài riêng.

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
└──────────────┬───────────────┘
               │ ws://127.0.0.1:9222
               ▼
┌──────────────────────────────┐
│ Chrome Extension (MV3)       │
└──────────────┬───────────────┘
               │ signed browser session
               ▼
          flow.google.com
```

## Yêu cầu hệ thống

- Windows 10/11
- Python 3.10 trở lên; khuyến nghị Python 3.11 hoặc 3.12
- Node.js 20 trở lên
- npm
- Google Chrome
- FFmpeg và FFprobe trong `PATH`
- Tài khoản có thể sử dụng Google Flow

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

## Cài Chrome Extension

1. Mở `chrome://extensions`.
2. Bật **Developer mode**.
3. Chọn **Load unpacked**.
4. Chọn thư mục `extension/` trong dự án.
5. Mở `https://flow.google.com/`, đăng nhập và giữ tab này hoạt động.
6. Tạo một project trên Flow và lấy UUID project từ URL.

Google Flow yêu cầu request được thực hiện trong tab trình duyệt đã đăng nhập,
vì vậy extension vẫn là thành phần bắt buộc khi sử dụng provider `flow`.

## Cấu hình

Thiết lập các biến môi trường trong cửa sổ PowerShell dùng để chạy backend:

```powershell
$env:FLOW_PROJECT_ID = "UUID_PROJECT_TREN_GOOGLE_FLOW"
$env:DEFAULT_PROVIDER = "flow"

$env:API_HOST = "127.0.0.1"
$env:API_PORT = "8100"
$env:WS_HOST = "127.0.0.1"
$env:WS_PORT = "9222"

$env:FLOW_GENERATION_MAX_CONCURRENT = "1"
$env:FLOW_GENERATION_MIN_INTERVAL_S = "3"
$env:FLOW_UNUSUAL_ACTIVITY_COOLDOWN_S = "3600"
$env:FLOWKIT_DEBUG_ENDPOINTS = "0"
```

Các biến trên chỉ tồn tại trong phiên PowerShell hiện tại. Sau khi thay đổi cấu
hình, hãy khởi động lại backend.

### Biến môi trường chính

| Biến | Mặc định | Mô tả |
|---|---:|---|
| `FLOW_PROJECT_ID` | trống | UUID project Google Flow; bắt buộc với provider `flow` |
| `DEFAULT_PROVIDER` | `flow` | Provider mặc định: `flow`, `assistant` hoặc `muse2api` |
| `API_HOST` | `127.0.0.1` | Địa chỉ bind FastAPI |
| `API_PORT` | `8100` | Port FastAPI |
| `WS_HOST` | `127.0.0.1` | Địa chỉ WebSocket dành cho extension |
| `WS_PORT` | `9222` | Port WebSocket dành cho extension |
| `FLOW_GENERATION_MAX_CONCURRENT` | `1` | Số tác vụ Flow gửi đồng thời |
| `FLOW_GENERATION_MIN_INTERVAL_S` | `3` | Khoảng nghỉ tối thiểu giữa các lần generate |
| `FLOW_UNUSUAL_ACTIVITY_COOLDOWN_S` | `3600` | Thời gian dừng khi Google phát hiện hoạt động bất thường |
| `FLOW_ALLOW_DEGRADED` | `0` | Cho phép chaining/r2v fallback xuống i2v |
| `FLOWKIT_DEBUG_ENDPOINTS` | `0` | Bật các endpoint debug; nên giữ `0` khi vận hành |

Các cấu hình nâng cao nằm trong [`agent/config.py`](agent/config.py).

## Khởi động ứng dụng

### 1. Khởi chạy toàn bộ ứng dụng

```powershell
cd dashboard
npm run electron:dev
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
Invoke-RestMethod http://127.0.0.1:8100/api/flow/status
Invoke-RestMethod http://127.0.0.1:8100/api/providers/status
```

`extension_connected` phải là `true` khi sử dụng Google Flow. Giá trị
`flow_key_present: false` là bình thường với transport hiện tại.

### 2. Chế độ phát triển

Mở một cửa sổ PowerShell khác:

```powershell
npm run electron:dev
```

Lệnh này chạy Vite và Electron đồng thời. DevTools tự mở trong chế độ phát
triển.

### 3. Chạy từ bản đã build

```powershell
cd dashboard
npm run build
npm run electron:start
```

### Chạy dashboard bằng trình duyệt

```powershell
cd dashboard
npm run dev
```

Truy cập `http://127.0.0.1:5173`.

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
10. Tạo thumbnail, metadata và upload YouTube
```

Nên gửi các tác vụ tạo media qua batch API để worker tự giới hạn concurrency:

```text
POST /api/requests/batch
GET  /api/requests/batch-status
```

Không nên tự tạo vòng lặp gửi request liên tục vì có thể kích hoạt cơ chế chống
lạm dụng của Google.

## API và tài liệu kỹ thuật

Khi backend đang chạy:

- Swagger UI: `http://127.0.0.1:8100/docs`
- Health check: `http://127.0.0.1:8100/health`
- Dashboard WebSocket: `ws://127.0.0.1:8100/ws/dashboard`
- Extension WebSocket: `ws://127.0.0.1:9222`

Tài liệu trong repository:

- [`ARCHITECTURE.md`](ARCHITECTURE.md): kiến trúc hệ thống
- [`dashboard/README.md`](dashboard/README.md): hướng dẫn riêng cho Electron UI
- [`CLAUDE.md`](CLAUDE.md): API và workflow chi tiết
- [`skills/`](skills/): các workflow `/fk-*`
- [`docs/CAPTURE.md`](docs/CAPTURE.md): ghi nhận payload Google Flow
- [`docs/IMAGE_API.md`](docs/IMAGE_API.md): API tạo ảnh

## Cấu trúc thư mục

```text
HBG-Video-Studio/
├── agent/          # FastAPI, worker, providers và SQLite
├── dashboard/      # React UI và Electron main/preload
│   ├── electron/
│   └── src/
├── extension/      # Chrome Extension Manifest V3
├── skills/         # Workflow dành cho AI coding agents
├── tools/          # Review board và công cụ hỗ trợ
├── youtube/        # OAuth và pipeline upload YouTube
├── docs/           # Tài liệu kỹ thuật
└── tests/          # Unit/integration tests
```

## Lưu ý an toàn tài khoản

Khi Google trả về `PUBLIC_ERROR_UNUSUAL_ACTIVITY`, FlowKit sẽ dừng các tác vụ
generate trong thời gian cooldown. Không nên xóa hold hoặc gửi lại liên tục khi
generation thủ công trên Google Flow vẫn chưa hoạt động.

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
