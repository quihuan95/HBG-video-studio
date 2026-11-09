import { useCallback, useEffect, useMemo, useState } from 'react'
import { CalendarDays, RefreshCw } from 'lucide-react'
import { fetchAPI } from '../api/client'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'

interface CalendarItem {
  id: string
  kind: 'topic' | 'post'
  profile_id: string
  profile_name: string
  topic_id: string | null
  topic_title: string | null
  date: string
  time: string
  status: string
  color: string
}

export default function ContentCalendarPage() {
  const [items, setItems] = useState<CalendarItem[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try { setItems(await fetchAPI<CalendarItem[]>('/api/calendar')); setError(null) }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
  }, [])
  useEffect(() => { void load() }, [load])

  const groups = useMemo(() => Object.entries(items.reduce<Record<string, CalendarItem[]>>((acc, item) => {
    const key = item.date || 'Chưa có ngày'; (acc[key] ??= []).push(item); return acc
  }, {})), [items])

  async function syncAll() {
    setBusy(true)
    try { await fetchAPI('/api/profiles/sync-all', { method: 'POST' }); await load() }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  async function createFromTopic(item: CalendarItem) {
    setBusy(true)
    try {
      await fetchAPI('/api/posts', { method: 'POST', body: JSON.stringify({ profile_id: item.profile_id, topic_id: item.topic_id }) })
      await load()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <div>
          <h1 className="m-0 text-lg font-semibold">Lịch nội dung</h1>
          <p className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>Topic từ Sheet và Post đã tạo được hợp nhất theo ngày/giờ.</p>
        </div>
        <Button className="ml-auto" size="sm" disabled={busy} onClick={syncAll}>
          <RefreshCw size={12} className={busy ? 'animate-spin' : undefined} /> Đồng bộ tất cả
        </Button>
      </div>
      {error && <div className="text-xs" style={{ color: 'var(--red)' }}>{error}</div>}
      {groups.length === 0 ? (
        <Card><CardContent className="py-8 text-center text-xs" style={{ color: 'var(--muted)' }}>Chưa có Topic hoặc Post trên lịch.</CardContent></Card>
      ) : groups.map(([day, dayItems]) => (
        <Card key={day} className="py-4">
          <CardHeader><CardTitle className="text-xs flex items-center gap-2"><CalendarDays size={13} />{day}</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2">
            {dayItems.map(item => (
              <div key={`${item.kind}-${item.id}`} className="flex items-center gap-3 rounded px-3 py-2 border" style={{ borderColor: 'var(--border)' }}>
                <span className="w-2 h-2 rounded-full" style={{ background: item.color }} />
                <span className="text-[11px] w-12">{item.time}</span>
                <div className="flex flex-col min-w-0">
                  <span className="text-xs truncate">{item.topic_title || 'Bài không gắn Topic'}</span>
                  <span className="text-[9px]" style={{ color: 'var(--muted)' }}>{item.profile_name} · {item.kind === 'topic' ? 'TOPIC CHƯA TẠO BÀI' : item.status}</span>
                </div>
                {item.kind === 'topic' && <Button className="ml-auto" size="xs" disabled={busy} onClick={() => createFromTopic(item)}>Tạo bài</Button>}
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
