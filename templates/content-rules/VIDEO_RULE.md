# VIDEO RULE

## 1. Đầu ra

- Tỷ lệ mặc định: 9:16.
- Độ phân giải: 1080 × 1920.
- Frame rate: 30 fps.
- Định dạng: MP4, H.264 video và AAC audio.
- Thời lượng mục tiêu: [ĐIỀN SỐ GIÂY HOẶC “THEO KỊCH BẢN”].

## 2. Quy tắc chia scene

- Mỗi scene phục vụ một ý narration rõ ràng.
- Timeline phải bám theo thời lượng voice thực tế.
- Không cắt mất đầu hoặc cuối câu.
- Scene ngắn nhất: [1.5] giây.
- Chuyển cảnh ưu tiên cut hoặc dissolve ngắn; không lạm dụng hiệu ứng.

## 3. Chọn footage

- Chỉ dùng footage trạng thái READY và liên quan trực tiếp tới nội dung voice.
- Ưu tiên quality score từ [7] trở lên và usable range đã được AI đánh dấu.
- Match theo subject, action, location, tag và visual intent của scene.
- Không dùng đoạn rung mạnh, out nét, cháy sáng hoặc có watermark lạ.
- Không lặp lại cùng một đoạn ở hai scene liền nhau nếu còn lựa chọn khác.
- Thiếu footage phù hợp phải tạo blocker `NEEDS_INPUT`, không dùng cảnh sai.

## 4. Voice

- Voice provider: OpenAI.
- Voice mặc định: lấy từ Production Profile.
- Tốc độ: [0.95–1.05].
- Giọng điệu: [CHUYÊN NGHIỆP / GẦN GŨI / NĂNG ĐỘNG].
- Chuẩn hóa cách đọc số, ngày, tên riêng và từ viết tắt trước khi tạo audio.

## 5. Subtitle và on-screen text

- Subtitle bám sát voice timing, tối đa hai dòng.
- Mỗi dòng khoảng 32–40 ký tự.
- Font: [TÊN FONT].
- Màu chữ và viền: [QUY TẮC MÀU].
- Giữ chữ trong safe zone, không che mặt, sản phẩm hoặc chi tiết chính.
- On-screen text chỉ nhấn mạnh từ khóa, không chép lại toàn bộ subtitle.

## 6. Logo

- Dùng logo từ Production Profile.
- Vị trí mặc định: [top-right / top-left / bottom-right / bottom-left].
- Chiều rộng: [8–12]% chiều rộng khung hình.
- Không kéo giãn, đổi màu hoặc làm logo mất tỷ lệ.

## 7. Nhạc và âm thanh

- Nhạc nền không được lấn voice.
- Music volume tham khảo: 0.10–0.18.
- Voice volume: 1.0.
- Fade in/out nhạc: [0.5–1.5] giây.
- Chỉ dùng nhạc có quyền sử dụng phù hợp.

## 8. Review trước export

- Hình ảnh có khớp narration từng scene không?
- Có scene nào thiếu footage, kéo dài giả tạo hoặc lặp footage không?
- Subtitle có sai chính tả, tràn khung hoặc lệch timing không?
- Logo có đúng vị trí và safe zone không?
- Voice có rõ, đủ câu và không bị nhạc lấn không?
- File cuối có đúng resolution, fps, duration và codec không?
