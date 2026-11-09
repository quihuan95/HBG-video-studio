import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Clock3, LoaderCircle, RefreshCw } from 'lucide-react'
import { fetchAPI } from '../api/client'
import { Button } from '../components/ui/button'
import { Card, CardContent } from '../components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs'

interface ContentItem {
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

const DONE = new Set(['MANUALLY_UPLOADED', 'COMPLETED', 'ARCHIVED'])

function ItemRow({ item, busy, onCreate }: { item: ContentItem; busy: boolean; onCreate: (item: ContentItem) => void }) {
  return <div className="flex items-center gap-3 px-3 py-2.5 rounded border" style={{ borderColor: 'var(--border)' }}>
    <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: item.color }} />
    <div className="flex flex-col min-w-0">
      <span className="text-xs truncate">{item.topic_title || 'Bài không gắn Topic'}</span>
      <span className="text-[9px]" style={{ color: 'var(--muted)' }}>{item.profile_name} · {item.date} {item.time} · {item.kind === 'topic' ? 'CHƯA TẠO' : item.status}</span>
    </div>
    {item.kind === 'topic' && <Button className="ml-auto" size="xs" disabled={busy} onClick={() => onCreate(item)}>Tạo bài</Button>}
  </div>
}

export default function PostManagementPage() {
  const [items, setItems] = useState<ContentItem[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    try { setItems(await fetchAPI<ContentItem[]>('/api/calendar')); setError(null) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }, [])
  useEffect(() => { void load() }, [load])
  const groups = useMemo(() => ({
    planned: items.filter(x => x.kind === 'topic'),
    working: items.filter(x => x.kind === 'post' && !DONE.has(x.status)),
    done: items.filter(x => x.kind === 'post' && DONE.has(x.status)),
  }), [items])
  async function create(item: ContentItem) {
    setBusy(true)
    try { await fetchAPI('/api/posts', { method: 'POST', body: JSON.stringify({ profile_id: item.profile_id, topic_id: item.topic_id }) }); await load() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  async function sync() {
    setBusy(true)
    try { await fetchAPI('/api/profiles/sync-all', { method: 'POST' }); await load() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  const panels = [
    ['planned', 'Sẽ tạo', groups.planned, Clock3],
    ['working', 'Đang làm', groups.working, LoaderCircle],
    ['done', 'Đã hoàn thành', groups.done, CheckCircle2],
  ] as const
  return <div className="flex flex-col gap-4">
    <div className="flex items-center"><div><h1 className="m-0 text-lg font-semibold">Quản lý bài</h1><p className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>Theo dõi toàn bộ bài sẽ tạo, đang xử lý và đã hoàn thành.</p></div><Button className="ml-auto" size="sm" disabled={busy} onClick={sync}><RefreshCw size={12} className={busy ? 'animate-spin' : undefined}/> Đồng bộ</Button></div>
    {error && <div className="text-xs" style={{ color: 'var(--red)' }}>{error}</div>}
    <Tabs defaultValue="planned">
      <TabsList>{panels.map(([key,label,list]) => <TabsTrigger key={key} value={key}>{label} ({list.length})</TabsTrigger>)}</TabsList>
      {panels.map(([key,,list,Icon]) => <TabsContent key={key} value={key}><Card className="py-4"><CardContent className="flex flex-col gap-2">{list.length ? list.map(item => <ItemRow key={`${item.kind}-${item.id}`} item={item} busy={busy} onCreate={create}/>) : <div className="py-8 text-center text-xs" style={{color:'var(--muted)'}}><Icon size={18} className="mx-auto mb-2"/>Không có bài trong nhóm này.</div>}</CardContent></Card></TabsContent>)}
    </Tabs>
  </div>
}
