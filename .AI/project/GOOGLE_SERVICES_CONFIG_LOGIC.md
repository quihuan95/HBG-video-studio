# Google Services Configuration & OAuth Logic

Tài liệu này mô tả logic cấu hình và kết nối Google Services để một AI coding agent có thể áp dụng lại cho một ứng dụng khác. Nội dung không chứa credential thật và không phụ thuộc vào giao diện của HBG Content Studio.

## 1. Mục tiêu

Ứng dụng cần:

- Kết nối tài khoản Google bằng OAuth 2.0 Authorization Code Flow.
- Xin quyền Google Drive, đọc Google Sheets và đọc thông tin tài khoản.
- Nhận `access_token` và `refresh_token` ở backend.
- Mã hóa token trước khi lưu database.
- Tự động refresh access token trước khi hết hạn.
- Theo dõi trạng thái kết nối: `active`, `needs_reconnect`, `not_connected`.
- Chống CSRF bằng OAuth `state` dùng một lần và có thời hạn.

## 2. Environment variables

Tạo các biến môi trường sau:

```env
# OAuth 2.0 Web/Desktop client do Google Cloud Console cấp
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# Phải trùng tuyệt đối với Authorized redirect URI trong Google Cloud Console
GOOGLE_REDIRECT_URI=http://localhost:8080/api/oauth/google/callback

# Khóa ngẫu nhiên 32 byte, biểu diễn bằng 64 ký tự hex
# Ví dụ tạo bằng: node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
TOKEN_ENCRYPTION_KEY=

# Tùy chọn: đường dẫn tới file .env
APP_ENV_PATH=
```

Không đưa `.env`, client secret, encryption key hoặc token vào Git. Với production, secret phải đến từ secret manager hoặc environment của hệ thống triển khai.

## 3. Cấu hình ứng dụng

Mapping đề xuất:

```js
export const googleConfig = {
  clientId: process.env.GOOGLE_CLIENT_ID || '',
  clientSecret: process.env.GOOGLE_CLIENT_SECRET || '',
  redirectUri:
    process.env.GOOGLE_REDIRECT_URI ||
    'http://localhost:8080/api/oauth/google/callback',
  scopes: [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
  ]
};
```

Ý nghĩa scope:

| Scope | Mục đích |
|---|---|
| `drive` | Đọc, tạo, cập nhật file và folder trên Google Drive |
| `spreadsheets.readonly` | Đọc dữ liệu Google Sheets, không chỉnh sửa Sheet |
| `userinfo.email` | Lấy email của tài khoản đã kết nối |
| `userinfo.profile` | Lấy tên và thông tin profile cơ bản |

Áp dụng nguyên tắc least privilege: nếu app chỉ cần đọc Drive, thay `drive` bằng scope chỉ đọc phù hợp. Không xin scope không dùng đến.

## 4. Điều kiện cấu hình hợp lệ

Backend phải từ chối khởi tạo OAuth nếu thiếu một trong các giá trị:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `TOKEN_ENCRYPTION_KEY`

Trong production, `TOKEN_ENCRYPTION_KEY` phải là đúng 64 ký tự hex. Không dùng secret mặc định hoặc tự fallback sang một chuỗi hard-code.

## 5. Database schema tối thiểu

Ví dụ SQL trung lập:

```sql
CREATE TABLE oauth_states (
  state TEXT PRIMARY KEY,
  user_id TEXT,
  redirect_uri TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE connections (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  user_id TEXT NOT NULL,
  encrypted_tokens TEXT NOT NULL,
  scopes TEXT NOT NULL,
  account_email TEXT,
  account_name TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  last_health_check TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (provider, user_id)
);
```

`encrypted_tokens` chứa JSON đã mã hóa với cấu trúc trước khi mã hóa:

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": 1790000000000
}
```

`expires_at` là Unix time theo milliseconds.

## 6. Luồng bắt đầu OAuth

Endpoint đề xuất:

```http
GET /api/oauth/google/start
```

Backend thực hiện:

1. Kiểm tra Google config đã đầy đủ.
2. Sinh `state` bằng cryptographically secure random, tối thiểu 24 byte.
3. Lưu `state`, `user_id`, `redirect_uri`, `created_at` và `expires_at` vào database.
4. Cho state hết hạn sau 15 phút.
5. Tạo URL authorize và trả URL cho frontend.

Thông số authorize:

```js
const params = new URLSearchParams({
  client_id: googleConfig.clientId,
  redirect_uri: googleConfig.redirectUri,
  response_type: 'code',
  scope: googleConfig.scopes.join(' '),
  access_type: 'offline',
  prompt: 'consent',
  state
});

const authUrl =
  `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`;
```

`access_type=offline` dùng để yêu cầu refresh token. `prompt=consent` giúp Google hiện lại màn hình consent và thường trả refresh token, nhưng có thể gây trải nghiệm đăng nhập lặp lại; app mới có thể chỉ dùng khi kết nối/reconnect chủ động.

Frontend nhận URL rồi điều hướng trình duyệt tới URL đó. Client không được tự tạo hoặc tự ký `state` nếu backend đang quản lý phiên OAuth.

## 7. Xử lý OAuth callback

Endpoint đề xuất:

```http
GET /api/oauth/google/callback?code=...&state=...
```

Backend xử lý theo đúng thứ tự:

1. Yêu cầu cả `code` và `state`.
2. Tìm bản ghi `state` trong database.
3. Xóa state ngay khi lấy ra để state chỉ dùng một lần.
4. Kiểm tra state chưa hết hạn.
5. Kiểm tra redirect URI lưu cùng state khớp với redirect URI đang dùng.
6. Đổi authorization code lấy token bằng backend-to-backend request.
7. Dùng access token lấy thông tin tài khoản.
8. Nếu Google không trả refresh token khi reconnect, giữ lại refresh token cũ của đúng user/provider.
9. Mã hóa token payload rồi upsert connection.
10. Redirect người dùng về trang settings/success của app.

Request đổi token:

```js
const response = await fetch('https://oauth2.googleapis.com/token', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({
    code,
    client_id: googleConfig.clientId,
    client_secret: googleConfig.clientSecret,
    redirect_uri: googleConfig.redirectUri,
    grant_type: 'authorization_code'
  })
});
```

Lấy profile:

```js
const response = await fetch(
  'https://www.googleapis.com/oauth2/v2/userinfo',
  { headers: { Authorization: `Bearer ${accessToken}` } }
);
```

Không gửi `client_secret`, authorization code, access token hoặc refresh token về frontend và không ghi chúng vào log.

## 8. Mã hóa token

Dùng AES-256-GCM:

- Key: 32 byte.
- IV: 12 byte ngẫu nhiên mới cho mỗi lần mã hóa.
- Authentication tag: lưu cùng ciphertext.
- Có thể lưu theo định dạng `iv:authTag:ciphertext`, với các phần được encode hex hoặc base64.

Pseudo-code:

```js
function encryptToken(plaintext, key) {
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  const ciphertext = Buffer.concat([
    cipher.update(plaintext, 'utf8'),
    cipher.final()
  ]);
  const authTag = cipher.getAuthTag();

  return [iv, authTag, ciphertext]
    .map(value => value.toString('base64'))
    .join(':');
}
```

Khi decrypt thất bại, không thử sử dụng token. Chuyển connection sang `needs_reconnect`.

## 9. Lấy access token hợp lệ

Mọi module Google Drive/Sheets phải gọi một hàm trung tâm, ví dụ `getValidAccessToken(userId)`, thay vì tự đọc token từ database.

Thuật toán:

```text
Tìm connection(provider = google, user_id, status = active)
  └─ Không có → trả null / lỗi NOT_CONNECTED

Giải mã token
  └─ Thất bại → status = needs_reconnect → trả null

Access token còn hạn trên 5 phút?
  ├─ Có → trả access token
  └─ Không → kiểm tra refresh token
       ├─ Không có → status = needs_reconnect → trả null
       └─ Có → gọi token endpoint với grant_type=refresh_token
            ├─ Thành công → cập nhật token + expires_at → mã hóa → lưu DB
            └─ invalid_grant/token bị thu hồi → status = needs_reconnect
```

Request refresh:

```js
const response = await fetch('https://oauth2.googleapis.com/token', {
  method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: new URLSearchParams({
    client_id: googleConfig.clientId,
    client_secret: googleConfig.clientSecret,
    refresh_token: tokens.refresh_token,
    grant_type: 'refresh_token'
  })
});
```

Sau refresh:

```js
tokens.access_token = data.access_token;
tokens.expires_at = Date.now() + (data.expires_in || 3600) * 1000;
if (data.refresh_token) tokens.refresh_token = data.refresh_token;
```

Giữ buffer 5 phút để tránh token hết hạn giữa một request dài. Với nhiều worker, dùng transaction/lock hoặc cơ chế single-flight để tránh nhiều tiến trình refresh cùng một token đồng thời.

## 10. Gọi Google Drive và Sheets

Mọi request dùng header:

```http
Authorization: Bearer <valid_access_token>
```

Base endpoints:

```text
Drive metadata: https://www.googleapis.com/drive/v3
Drive upload:   https://www.googleapis.com/upload/drive/v3
Sheets:         https://sheets.googleapis.com/v4
```

Nếu API trả `401`, có thể invalidate access token và thử refresh đúng một lần. Không retry vô hạn. Với `403`, phân biệt thiếu scope/quyền truy cập với quota/rate limit.

## 11. Connection status API

API status chỉ trả metadata an toàn:

```json
{
  "provider": "google",
  "accountEmail": "user@example.com",
  "accountName": "Example User",
  "status": "active",
  "lastHealthCheck": "2026-11-09T00:00:00.000Z",
  "updatedAt": "2026-11-09T00:00:00.000Z"
}
```

Không trả `encrypted_tokens`, access token, refresh token, client secret hoặc encryption key.

## 12. Desktop/Electron app

Nếu app chạy local desktop, redirect URI có thể được đặt ở runtime:

```js
process.env.GOOGLE_REDIRECT_URI =
  'http://127.0.0.1:8080/api/oauth/google/callback';
```

Các lưu ý:

- URI trong app và Google Cloud Console phải giống tuyệt đối, kể cả `localhost` so với `127.0.0.1`, port, protocol và path.
- Dùng port cố định nếu redirect URI đã đăng ký với port cố định.
- Chỉ bind local backend vào loopback interface nếu không cần truy cập từ máy khác.
- Mở authorize URL bằng system browser; callback quay về local backend.
- File `.env` của desktop app phải nằm trong thư mục user data hoặc secret store, không đóng gói secret vào frontend bundle.

## 13. Security checklist

- [ ] OAuth exchange và refresh chỉ chạy ở backend.
- [ ] Validate config khi khởi động hoặc trước khi bắt đầu OAuth.
- [ ] `state` đủ ngẫu nhiên, hết hạn, lưu server-side và chỉ dùng một lần.
- [ ] Redirect URI khớp tuyệt đối và nằm trong allowlist.
- [ ] Token được mã hóa bằng AES-256-GCM với key production riêng.
- [ ] Không có encryption-key fallback hard-code trong production.
- [ ] Không log code, token, secret hoặc toàn bộ response từ token endpoint.
- [ ] Không trả token hoặc encrypted token qua API status/settings.
- [ ] Refresh token cũ chỉ được giữ lại cho đúng `provider + user_id`.
- [ ] Xử lý `invalid_grant` bằng `needs_reconnect`.
- [ ] Có timeout cho mọi request tới Google.
- [ ] Có retry giới hạn với backoff cho `429` và lỗi `5xx` phù hợp.
- [ ] Scope tuân theo least privilege.
- [ ] Settings UI che secret và không ghi đè secret hiện tại bằng chuỗi rỗng ngoài ý muốn.
- [ ] Có cơ chế disconnect: revoke token nếu phù hợp, sau đó xóa token đã lưu.

## 14. Acceptance criteria cho AI coding agent

Chỉ coi tính năng hoàn thành khi:

1. Có module config tập trung và validate đầy đủ.
2. Có migration/schema cho `oauth_states` và `connections`.
3. Có endpoint start và callback với CSRF state protection.
4. Authorization code được exchange ở backend.
5. Token được mã hóa authenticated encryption trước khi lưu.
6. Refresh token được bảo toàn nếu reconnect không trả token mới.
7. Có hàm duy nhất cung cấp valid access token cho Drive/Sheets.
8. Connection chuyển sang `needs_reconnect` khi decrypt/refresh thất bại không thể phục hồi.
9. Status API không làm lộ secret/token.
10. Có test cho state không hợp lệ, state hết hạn, token còn hạn, token cần refresh, refresh thất bại và reconnect không trả refresh token.
11. Có tài liệu setup Google Cloud Console và redirect URI cho môi trường chạy thực tế.
12. Không commit credential thật trong source code, fixture hoặc test snapshot.

## 15. Prompt ngắn để giao cho AI coding

```text
Hãy triển khai Google OAuth 2.0 và Google Services theo tài liệu
GOOGLE_SERVICES_CONFIG_LOGIC.md.

Yêu cầu:
- Giữ nguyên kiến trúc và conventions của app hiện tại.
- OAuth Authorization Code Flow chạy hoàn toàn ở backend.
- Dùng server-side one-time state hết hạn sau 15 phút.
- Xin offline access cho Drive, Sheets read-only và user info.
- Mã hóa token bằng AES-256-GCM trước khi lưu database.
- Tạo một hàm trung tâm getValidAccessToken có buffer hết hạn 5 phút.
- Không làm lộ secret/token qua frontend, API response hoặc log.
- Thêm migration, validation, error handling và automated tests.
- Nếu framework/ngôn ngữ khác ví dụ Node.js trong tài liệu, hãy chuyển đổi
  tương đương theo best practices của stack đang dùng.
- Trước khi sửa code, hãy liệt kê file sẽ tạo/sửa và các giả định kỹ thuật.
```

