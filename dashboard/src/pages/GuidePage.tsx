import { Bot, CalendarDays, CheckCircle2, Clapperboard, Cloud, FileVideo, Play } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card'

const STEPS = [
  {
    icon: Bot,
    title: '1. Cấu hình OpenAI',
    body: 'Vào Cài đặt → OpenAI, nhập API key và chọn model cho phân loại footage, video review, viết kịch bản và text-to-speech. Lưu rồi khởi động lại ứng dụng.',
  },
  {
    icon: Cloud,
    title: '2. Kết nối Google',
    body: 'Trong Cài đặt → Google Drive & Sheets, bấm Kết nối Google và hoàn tất consent trên trình duyệt. Ứng dụng dùng kết nối này để đọc Rule, Sheet, footage Drive và tải đầu ra.',
  },
  {
    icon: CalendarDays,
    title: '3. Tạo Content Profile',
    body: 'Mở Content Profiles, nhập tên thương hiệu, timezone, giờ mặc định, folder RULES và Sheet TOPICS. Chọn workflow manual, semi_auto hoặc auto rồi đồng bộ Rule + Sheet.',
  },
  {
    icon: FileVideo,
    title: '4. Chuẩn bị footage',
    body: 'Thêm folder footage local hoặc Google Drive vào Profile. Chạy scan để lập thư viện, sau đó dùng OpenAI phân loại nội dung, chất lượng, tag và khoảng hình có thể sử dụng.',
  },
  {
    icon: Clapperboard,
    title: '5. Tạo nội dung theo lịch',
    body: 'Mở Lịch nội dung. Topic đồng bộ từ Sheet xuất hiện theo ngày/giờ; bấm Tạo bài để tạo Post và snapshot Rule. Post sẽ thay Topic trên cùng slot lịch.',
  },
  {
    icon: CheckCircle2,
    title: '6. Sản xuất và xuất video',
    body: 'Dùng kịch bản để tạo voice, chọn và cắt footage, thêm nhạc, logo, phụ đề rồi export. Thành phẩm được đưa vào folder Drive đầu ra của Profile.',
  },
]

const CHECKS = [
  ['Ứng dụng không khởi động', 'Chạy npm run dev từ thư mục gốc. Lần đầu clone hãy chạy npm run install:dashboard.'],
  ['OpenAI không hoạt động', 'Kiểm tra API key trong Cài đặt → OpenAI, bấm lưu và khởi động lại ứng dụng.'],
  ['Không kết nối được Google', 'Redirect URI phải là http://127.0.0.1:8100/api/oauth/google/callback và phải trùng tuyệt đối trong Google Cloud Console.'],
  ['Không thấy Topic trên lịch', 'Kiểm tra tab TOPICS có topic_id, content_date, publish_time, topic_title rồi chạy Đồng bộ Rule + Sheet.'],
  ['Không tạo được Post', 'Profile phải có ít nhất một Rule version đã published. Kiểm tra folder RULES hoặc tạo Rule qua API trước.'],
  ['Footage không được nhận diện', 'Kiểm tra đường dẫn folder, quyền Drive và ffmpeg/ffprobe đã có trong PATH.'],
]

export default function GuidePage() {
  return (
    <div className="flex flex-col gap-5 max-w-4xl">
      <div>
        <h1 className="m-0 text-lg font-semibold">Hướng dẫn HBG Video Studio</h1>
        <p className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>
          Quy trình hiện tại dùng OpenAI, Google Drive/Sheets, footage và lịch nội dung; không cần Chrome Extension hay mở Google Flow.
        </p>
      </div>

      <Card className="py-4">
        <CardHeader>
          <CardTitle className="text-xs tracking-widest uppercase flex items-center gap-2"><Play size={13} /> Khởi động</CardTitle>
          <CardDescription className="text-[11px]">Chạy toàn bộ Electron, frontend, backend và worker bằng một lệnh.</CardDescription>
        </CardHeader>
        <CardContent>
          <code className="block rounded px-3 py-2 text-xs" style={{ background: 'var(--bg)', color: 'var(--accent)' }}>npm run dev</code>
        </CardContent>
      </Card>

      <div className="grid grid-cols-2 gap-3">
        {STEPS.map(({ icon: Icon, title, body }) => (
          <Card key={title} className="py-4">
            <CardContent className="flex gap-3">
              <Icon size={17} className="flex-shrink-0 mt-0.5" style={{ color: 'var(--accent)' }} />
              <div><div className="text-xs font-semibold">{title}</div><div className="text-[11px] mt-1 leading-relaxed" style={{ color: 'var(--muted)' }}>{body}</div></div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="py-4">
        <CardHeader><CardTitle className="text-xs tracking-widest uppercase">Xử lý sự cố</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3">
          {CHECKS.map(([problem, solution]) => (
            <div key={problem} className="pb-3 border-b last:border-0 last:pb-0" style={{ borderColor: 'var(--border)' }}>
              <div className="text-xs font-semibold">{problem}</div>
              <div className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>{solution}</div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
