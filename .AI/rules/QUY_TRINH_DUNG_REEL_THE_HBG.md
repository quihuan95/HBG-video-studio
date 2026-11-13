# Quy trình dựng reel The HBG bằng JSX (After Effects)

_Cập nhật 06/11/2026 (sau video M.I.C.E "Ba góc máy cần có trong lễ ký kết", tham chiếu `D:\1106_3 góc máy\VIDEO_3GocMay_v5.md`)._

Tài liệu chuẩn cho mọi chat trong project VIDEO MARKETING. Đọc file này trước khi dựng video mới.
Template code: `templates/HBG_reel_template_GianHang_v3.jsx` (bản đã chạy được, dùng làm khung; khối hotline và vị trí phụ đề trong template là bản cũ — thay theo bố cục chữ phía dưới ở mục 0).
Script số điện thoại chuẩn: `templates/TAO_HOTLINE_HBG.jsx` (bản trên máy: `D:\TRAM_TAI\HBG_SCRIPTS\TAO_HOTLINE_HBG.jsx`) — chạy trên comp đang mở, tạo/cập nhật layer `PHONE_TXT` + `PHONE_PILL`, tắt hotline cũ, dời phụ đề `SUB_*` xuống dưới khung. Khi dựng video mới, gọi lại logic này thay cho khối hotline của template.

## 0. Chuẩn duyệt của chị Hà (Ha Do) — áp dụng mặc định cho mọi video (The HBG Tourist và The HBG M.I.C.E dùng chung format)
- **100% xử lý trong JSX:** mọi hiệu ứng và xử lý (cắt/ghép VO theo câu, khoảng nghỉ, cắt nhạc theo drop, Time Stretch, crop, nền blur, mức âm) nằm trong script AE để người dùng tự chạy. Claude KHÔNG tự render video xem trước, KHÔNG tự xử lý/generate VO hay file nhạc. Claude chỉ được phân tích (đo BPM, khoảng lặng, loudness, contact sheet) để tính thông số đưa vào JSX. JSX đọc thẳng file gốc: VO mp3 ElevenLabs trong `Source\VO`, nhạc trong `Source\Music_raw`, footage trong `Source\Footage`, SFX trong `Source\SFX` (thiếu thì lấy ở `D:\AEJuice Sound Effects Pro`).
- **Bố cục chữ phía dưới (chuẩn đã duyệt 04/11, từ trên xuống):** khung tên địa điểm (khi có) → **khung số điện thoại** → **phụ đề ngay bên dưới số điện thoại**. Không chồng nhau, không đặt chữ giữa hình.
  - **Số điện thoại:** `(+84) 939.311.911 - (+84) 913.311.911` (không có chữ "Hotline:"). Khung xanh `#253E89` dạng viên thuốc bo tròn hết, chữ vàng `#d9a65a`, Montserrat ExtraBold ~30px (thiếu font thì Arial Bold), padding ~22px ngang / ~10px dọc. Giữa ngang (x=540), tâm y≈1360, căn giữa. Hiện xuyên suốt 0s → lúc vào outro, không animation. Không đặt dưới logo; không hỏi lại về số điện thoại.
  - **Phụ đề:** trắng viền đen ~40px, căn giữa x=540, mép trên y≈1405 (ngay dưới khung số điện thoại, cách ~15px), tối đa 2 dòng.
  - **Khung tên địa điểm:** mép dưới y≈1310 (ngay trên khung số điện thoại).
- **Tốc độ VO giữ nguyên x1 (duyệt 06/11):** KHÔNG tăng tốc VO trong AE — Time Stretch trên layer âm thanh làm giọng cao và méo (đã thử 1.15 và 1.1 đều méo). Muốn nhanh hơn thì chỉnh Speed ngay trong ElevenLabs khi gen.
- **Nhịp vừa phải, không dồn dập:** tách VO thành từng câu (mỗi câu 1 layer `VO_01…`), đặt lại vị trí để khoảng nghỉ giữa các câu ~0.15–0.4s (ngắn hơn khoảng nghỉ gốc của ElevenLabs, nhưng không dính liền). Mỗi chương: điểm cắt hình trên beat, lời bắt đầu 0–0.25s sau điểm cắt.
- **Nhạc:** có thể Time Stretch nhạc (vd x1.15 cho nhịp nhanh, drop đặt đúng hết câu hook bằng `startTime = drop_comp - drop_src/rate`); nếu nghe méo thì dùng tốc độ gốc và tính lưới beat theo BPM gốc.
- **Ít chữ:** đã có phụ đề thì không đặt khung chữ lặp lời voice. Chỉ giữ khung **tên địa điểm / tên hạng mục chính** (1 dòng, không dòng mô tả), hiện ~2.5s rồi mờ đi. Không làm khung câu hỏi hook, bảng so sánh, danh sách, CTA dài (nếu có thì để tắt). Số điện thoại không tính (luôn hiện).
- **Source khớp đúng nội dung và đẹp:** vd "ngân hạnh lá vàng" phải là ngân hạnh vàng ruộm thật; kiểm tra bằng contact sheet.
- **Video Trung Quốc lấy source nền tảng Trung Quốc:** Xiaohongshu (cần link "Chia sẻ" của bài video, có xsec_token; link từ Google thường lỗi "No video formats found") hoặc Bilibili (yt-dlp tải được; tránh watermark giữa hình).
- **Cảnh rộng bị hẹp khi cắt 9:16:** thu nhỏ vừa ngang khung + nền là chính clip phóng to, blur ~70, tối đi ~-30.

## 1. Đầu vào
- Kịch bản/brief: Google Sheet (vd "Bích Hiển - Brief video 2026", "Kịch bản reel"), mỗi tab là 1 video.
- Mỗi video có folder riêng trên ổ D của máy studio-minh, vd `D:\1103_ GIAN HANG TRIEN LAM\`:
  - `Source\Footage` (video nguồn), `Source\SFX`, `Source\Music`, `Source\VO`, logo + outro trong `Source`.
- Người dùng phải kết nối folder dự án vào chat (và `D:\AEJuice Sound Effects Pro` nếu cần SFX).
- Trước khi dựng: liệt kê từng tiêu chí của brief và **xác nhận với người dùng** (thời lượng, VO hay chỉ chữ, logo/outro, folder).

## 2. Format chuẩn
- 1080x1920, 30fps, footage tự "cover" khung 9:16 + Ken Burns 100→108% (expression); cảnh rộng dùng khung thu nhỏ + nền blur (mục 0).
- Chữ màu `#d9a65a` trong khung xanh `#253E89` (opacity 92, bo góc 16), khung tự co giãn theo chữ, pop-in scale 86→104→100.
- Bố cục chữ phía dưới theo mục 0 (tên địa điểm → số điện thoại → phụ đề).
- Safezone TikTok: L60 R960 T150 B1480.
- Logo: file `Logo only - 9x16.png` (full khung 3000x5333, logo góc trên trái) xuyên suốt tới hết phần chính; kết bằng `outro the hbg.mp4` (~3s).
- Font chữ đã duyệt: **Montserrat ExtraBold cho TẤT CẢ chữ** — tên chương/địa điểm, nhãn, phụ đề, số điện thoại (fallback Arial-BoldMT, script báo font đã dùng). Phụ đề Montserrat ExtraBold 40px thì ngắt dòng ~30 ký tự.
- Chọn đoạn source bằng contact sheet, kiểm tra khung đầu/giữa/cuối mỗi shot; nếu người dùng muốn tự cắt thì đặt clip từ đầu video nguồn và ghi "gợi ý m:ss". Footage tắt tiếng.

## 3. Âm thanh
- VO ElevenLabs (giọng Tuan Anh) thường chỉ ~-21 LUFS, đỉnh ~-1.7 dBTP. Trong AE không chuẩn hoá LUFS được: đặt gain VO ~+1.5 dB (không vượt 0 dB), nhạc ~-19.5 dB, SFX hạ thêm ~3.5 dB so với bảng mức dưới; khi xuất qua Media Encoder bật Loudness Normalization (-16 LUFS, hoặc -14 cho TikTok). Nếu người dùng gen lại 1 đoạn, ghép tại khoảng lặng giữa 2 câu.
- Nếu brief chưa có lời VO: Claude viết lời VO (tiếng Việt cho khách trong nước), người dùng tự gen ElevenLabs và đặt file vào `Source\VO`.
- Đo khoảng lặng VO (silencedetect -38dB, 0.15s) → căn phụ đề và điểm chuyển đoạn theo khoảng lặng thật; kiểm tra lại mọi điểm cắt (trừ montage) rơi vào khoảng lặng sau khi đặt lại vị trí câu.
- Nhạc: drop/beat mạnh rơi đúng lúc hết câu hook; mọi điểm cắt nằm trên lưới beat `drop + k×beat` (tự dò BPM bằng spectral flux). Nhạc dưới VO, hạ ~3 dB dưới câu CTA, fade trước outro. Tải 2–3 bản (MUSIC_A/B/C) vì hay có bản lỗi; nhạc corporate dùng Audio Library / Pavetraxx, ghi credit khi đăng YouTube.
- SFX ưu tiên thư viện `D:\AEJuice Sound Effects Pro` (pop_*, click_pop_up_*, keyboard_*_typing_*, small_whoosh_fast_*, medium_whoosh_*, whoosh_hit_*, click_tick*). Quy tắc: chữ hiện → pop/typing; chuyển đoạn → whoosh (căn đỉnh âm vào điểm cắt); cắt nhỏ → tick xen kẽ; không lặp liên tiếp cùng 1 file. Mức: whoosh -9/-12, pop -8, typing -15/-16, tick -13/-14.

## 4. Tải source
- Trạm tải tự động `D:\TRAM_TAI\BAT_TRAM_TAI.bat` (yt-dlp + ffmpeg trên máy, chỉ chạy 1 cửa sổ; job lỗi tự chuyển sang `done\*_LOI.txt`). Claude thả file job `.txt` vào `<project>\_queue\`, mỗi dòng `TEN_FILE | LINK | 0:00-8:00`, dòng `@OUT Source\Music_raw` để đổi thư mục. Kết quả trong `_queue\status.txt`.
- Luôn dùng **tên file mới** khi commit (công cụ commit đôi khi chép bản cũ khi ghi đè cùng đường dẫn); sau commit, stage lại và so sánh.
- Chỉ dùng hạng mục có thật trong source; bỏ video không đúng chủ đề hoặc có chữ chèn sẵn.

## 4b. Kỹ thuật đã dùng (video 3 góc máy)
- **Chia màn hình 3 góc (3-angle split):** 3 bảng ngang y 0–600 / 600–1200 / 1200–1920; mỗi bảng là layer footage cover theo bảng + mask chữ nhật (tính trong toạ độ layer), slide-in 0.22s, chạy chậm 75% (stretch 133%) để 1 shot ~1.3s đủ phủ 1.7s; vạch vàng `#d9a65a` 6px chia bảng; nhãn mỗi bảng góc trên phải (Montserrat 34px, khung xanh). Dùng lúc drop (bảng hiện lần lượt theo beat) và end frame.
- **Clip bản tin TV (khung chữ/ticker):** crop phần hình bằng mask trên layer gốc + nền blur, không render file crop riêng.
- **Brief M.I.C.E / MEDIA** (Sheet "Bích Hiển - Brief video 2026"): chỉ ĐỌC Sheet, không tạo kịch bản mới trên Sheet. Video tiếng Việt, caption đủ từ khoá bắt buộc của brief. Logo/outro: người dùng tự đặt vào `Source` (không tự copy từ dự án khác).

## 5. Lưu ý ExtendScript đã gặp
- Sau mỗi `addProperty` trên shape layer, lấy lại tham chiếu từ layer (tham chiếu cũ bị "Object is invalid").
- Expression engine JS: dùng `sub(a,b)` / `[v[0]*k, v[1]*k]`, không trừ/nhân mảng trực tiếp.
- `comp.workAreaDuration = comp.duration` (không dùng tổng tự tính, lỗi làm tròn).
- File .jsx lưu UTF-8 có BOM nếu có tiếng Việt; khai báo function không đặt trong khối if.
- Time Stretch layer: đặt `layer.stretch` trước, rồi `startTime`, `inPoint`, `outPoint`. Với VO tách câu: `startTime = vị_trí_lời_trong_comp - giây_lời_trong_file/rate`.
- Sửa video đã dựng: viết JSX vá vào comp có sẵn, giữ đoạn source đã chọn (`inPoint - startTime`), retime keyframe + marker, chặn chạy 2 lần, tắt layer thay vì xoá. Khi chỉnh layer chữ, đặt rõ opacity 100 và xoá key/expression cũ để tránh chữ bị ẩn.

## 6. Bàn giao
- Mỗi lần sửa ra bản JSX mới `_v<n+1>` (comp `_v<n+1>`), giữ bản cũ; cập nhật file `VIDEO_<Tên>_v<n>.md` tương ứng (ghi rõ thay đổi từng bản). Không kèm video preview.
- JSX dựng cả comp + marker từng đoạn; báo bảng đối chiếu từng tiêu chí brief và chuẩn duyệt mục 0; gợi ý caption TikTok đủ từ khoá bắt buộc.
- Xuất: H.264, 1080x1920, 30fps, 16–20 Mbps.
