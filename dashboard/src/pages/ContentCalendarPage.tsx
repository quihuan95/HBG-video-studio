import { useCallback, useEffect, useMemo, useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight, Clock3, RefreshCw } from 'lucide-react'
import { fetchAPI } from '../api/client'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'

interface CalendarItem {
  id: string
  kind: 'topic' | 'job'
  profile_id: string
  profile_name: string
  topic_id: string | null
  topic_title: string | null
  date: string
  time: string
  status: string
  color: string
  footage_status?: string | null
}
type FootageMode = 'DRIVE_ONLY' | 'INTERNET_ONLY' | 'HYBRID'

const WEEKDAYS = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']
const pad = (value: number) => String(value).padStart(2, '0')
const dateKey = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
const todayKey = () => dateKey(new Date())

export default function ContentCalendarPage() {
  const [items, setItems] = useState<CalendarItem[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [month, setMonth] = useState(() => { const now = new Date(); return new Date(now.getFullYear(), now.getMonth(), 1) })
  const [selectedDate, setSelectedDate] = useState(todayKey)

  const load = useCallback(async () => {
    try { setItems((await fetchAPI<CalendarItem[]>('/api/production-calendar')).filter(item => item.status !== 'CANCELLED')); setError(null) }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
  }, [])
  useEffect(() => { void load() }, [load])

  const byDate = useMemo(() => items.reduce<Record<string, CalendarItem[]>>((result, item) => {
    if (item.date) (result[item.date] ??= []).push(item)
    return result
  }, {}), [items])
  const unscheduled = useMemo(() => items.filter(item => !item.date), [items])
  const profiles = useMemo(() => Array.from(new Map(items.map(item => [item.profile_id, item])).values()), [items])
  const selectedItems = byDate[selectedDate] || []
  const calendarDays = useMemo(() => {
    const firstOffset = (month.getDay() + 6) % 7
    const start = new Date(month.getFullYear(), month.getMonth(), 1 - firstOffset)
    return Array.from({ length: 42 }, (_, index) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + index))
  }, [month])

  function moveMonth(offset: number) {
    const next = new Date(month.getFullYear(), month.getMonth() + offset, 1)
    setMonth(next); setSelectedDate(dateKey(next))
  }

  async function syncAll() {
    setBusy(true)
    try { await fetchAPI('/api/profiles/sync-all', { method: 'POST' }); await load() }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  async function schedule(item: CalendarItem) {
    setBusy(true)
    try {
      const endpoint = item.kind === 'topic' ? `/api/video-topics/${item.id}/schedule` : `/api/production-jobs/${item.id}/schedule`
      await fetchAPI(endpoint, { method: 'PATCH', body: JSON.stringify({ date: selectedDate, time: item.time || '09:00' }) })
      await load()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  async function createFromTopic(item: CalendarItem, footageMode: FootageMode) {
    setBusy(true)
    try {
      await fetchAPI('/api/production-jobs', { method: 'POST', body: JSON.stringify({ profile_id: item.profile_id, video_topic_id: item.topic_id, production_date: item.date, scheduled_time: item.time || '09:00', footage_mode: footageMode }) })
      await load()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  return <div className="flex flex-col gap-4">
    <div className="flex items-center gap-3">
      <div><h1 className="m-0 text-lg font-semibold">Lịch sản xuất</h1><p className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>Mỗi chấm là một video; màu chấm tương ứng với màu Production Profile.</p></div>
      <Button className="ml-auto" size="sm" disabled={busy} onClick={syncAll}><RefreshCw size={12} className={busy ? 'animate-spin' : undefined}/> Đồng bộ tất cả</Button>
    </div>
    {error && <div className="text-xs" style={{ color: 'var(--red)' }}>{error}</div>}

    <Card className="py-4"><CardHeader><div className="flex items-center gap-2">
      <Button size="icon-xs" variant="outline" onClick={() => moveMonth(-1)}><ChevronLeft/></Button>
      <CardTitle className="text-sm min-w-40 text-center">Tháng {month.getMonth() + 1}/{month.getFullYear()}</CardTitle>
      <Button size="icon-xs" variant="outline" onClick={() => moveMonth(1)}><ChevronRight/></Button>
      <Button size="xs" variant="ghost" onClick={() => { const now = new Date(); setMonth(new Date(now.getFullYear(), now.getMonth(), 1)); setSelectedDate(todayKey()) }}>Hôm nay</Button>
      <div className="ml-auto flex flex-wrap justify-end gap-x-3 gap-y-1">{profiles.map(profile => <span key={profile.profile_id} className="text-[9px] flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: profile.color }}/>{profile.profile_name}</span>)}</div>
    </div></CardHeader><CardContent>
      <div className="grid grid-cols-7 border-l border-t" style={{ borderColor: 'var(--border)' }}>
        {WEEKDAYS.map(day => <div key={day} className="py-2 text-center text-[9px] font-semibold border-r border-b" style={{ borderColor: 'var(--border)', color: 'var(--muted)' }}>{day}</div>)}
        {calendarDays.map(day => {
          const key = dateKey(day); const dayItems = byDate[key] || []; const inMonth = day.getMonth() === month.getMonth(); const selected = key === selectedDate
          return <button key={key} onClick={() => setSelectedDate(key)} className="min-h-20 p-2 text-left border-r border-b transition-colors" style={{ borderColor: selected ? 'var(--accent)' : 'var(--border)', background: selected ? 'var(--card)' : 'transparent', opacity: inMonth ? 1 : 0.4 }}>
            <span className="text-[10px]" style={{ color: key === todayKey() ? 'var(--accent)' : 'var(--text)' }}>{day.getDate()}</span>
            <div className="mt-2 flex flex-wrap gap-1.5">{dayItems.map(item => <span key={`${item.kind}-${item.id}`} title={`${item.time || '--:--'} · ${item.profile_name} · ${item.topic_title}`} className="w-2 h-2 rounded-full" style={{ background: item.color }}/>)}</div>
            {dayItems.length > 0 && <div className="mt-1 text-[8px]" style={{ color: 'var(--muted)' }}>{dayItems.length} video</div>}
          </button>
        })}
      </div>
    </CardContent></Card>

    <div className="grid grid-cols-2 gap-4">
      <Card className="py-4"><CardHeader><CardTitle className="text-xs flex items-center gap-2"><CalendarDays size={13}/>{selectedDate} · {selectedItems.length} video</CardTitle></CardHeader><CardContent className="flex flex-col gap-2">
        {selectedItems.length ? selectedItems.map(item => <CalendarRow key={`${item.kind}-${item.id}`} item={item} busy={busy} onCreate={createFromTopic}/>) : <div className="py-6 text-center text-xs" style={{ color: 'var(--muted)' }}>Ngày này chưa có lịch sản xuất.</div>}
      </CardContent></Card>
      <Card className="py-4"><CardHeader><CardTitle className="text-xs flex items-center gap-2"><Clock3 size={13}/>Chưa xếp lịch ({unscheduled.length})</CardTitle></CardHeader><CardContent className="flex flex-col gap-2 max-h-72 overflow-auto">
        {unscheduled.length ? unscheduled.map(item => <div key={`${item.kind}-${item.id}`} className="flex items-center gap-2 rounded border px-3 py-2" style={{ borderColor: 'var(--border)' }}><span className="w-2 h-2 rounded-full" style={{ background: item.color }}/><span className="text-[10px] truncate">{item.topic_title}</span><Button className="ml-auto" size="xs" disabled={busy} onClick={() => schedule(item)}>Xếp vào {selectedDate}</Button></div>) : <div className="py-6 text-center text-xs" style={{ color: 'var(--muted)' }}>Tất cả video đã được xếp lịch.</div>}
      </CardContent></Card>
    </div>
  </div>
}

function CalendarRow({ item, busy, onCreate }: { item: CalendarItem; busy: boolean; onCreate: (item: CalendarItem, mode: FootageMode) => void }) {
  const [footageMode, setFootageMode] = useState<FootageMode>('HYBRID')
  const canCreate = item.kind === 'topic'
  return <div className="flex items-center gap-3 rounded px-3 py-2 border" style={{ borderColor: 'var(--border)' }}>
    <span className="w-2 h-2 rounded-full" style={{ background: item.color }}/><span className="text-[11px] w-12">{item.time || '--:--'}</span>
    <div className="flex flex-col min-w-0"><span className="text-xs truncate">{item.topic_title || 'Video không gắn tab nguồn'}</span><span className="text-[9px]" style={{ color: 'var(--muted)' }}>{item.profile_name} · {item.kind === 'topic' ? 'CHƯA TẠO' : item.status}</span></div>
    {item.kind === 'topic' && <><select className="ml-auto rounded border bg-transparent px-2 py-1 text-[10px]" style={{ borderColor: 'var(--border)' }} value={footageMode} onChange={event => setFootageMode(event.target.value as FootageMode)} disabled={busy}><option value="DRIVE_ONLY">100% Drive</option><option value="INTERNET_ONLY">100% Internet</option><option value="HYBRID">Drive + Internet</option></select><Button size="xs" disabled={busy || !canCreate} title="Tạo voice trước, sau đó tìm footage theo nguồn đã chọn" onClick={() => onCreate(item, footageMode)}>Tạo video</Button></>}
  </div>
}
