import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Clock3, ExternalLink, FolderSearch2, LoaderCircle, RefreshCw, UploadCloud } from 'lucide-react'
import { fetchAPI } from '../api/client'
import { Button } from '../components/ui/button'
import { Card, CardContent } from '../components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs'

interface ContentItem {
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
  output_url?: string | null
  footage_folder_url?: string | null
  footage_status?: string | null
}

interface ClassificationRun {
  video_topic_id: string
  status: 'IDLE' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  stage: string
  message: string
  current: number
  total: number
  logs: { time: string; stage: string; message: string }[]
}

const DONE = new Set(['MANUALLY_UPLOADED', 'COMPLETED', 'ARCHIVED'])

function ItemRow({ item, busy, run, onCreate, onExport, onClassify }: { item: ContentItem; busy: boolean; run?: ClassificationRun; onCreate: (item: ContentItem) => void; onExport: (item: ContentItem) => void; onClassify: (item: ContentItem) => void }) {
  const running = run?.status === 'RUNNING'
  const percent = run?.total ? Math.round((run.current / run.total) * 100) : 0
  return <div className="flex flex-col gap-2 px-3 py-2.5 rounded border" style={{ borderColor: 'var(--border)' }}>
    <div className="flex items-center gap-3">
      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: item.color }} />
      <div className="flex flex-col min-w-0">
        <span className="text-xs truncate">{item.topic_title || 'Video không gắn tab nguồn'}</span>
        <span className="text-[9px]" style={{ color: 'var(--muted)' }}>{item.profile_name} · {item.date} {item.time} · {item.kind === 'topic' ? `FOOTAGE: ${running ? run.stage : item.footage_status || 'PENDING'}` : item.status}</span>
      </div>
      {item.kind === 'topic' && item.footage_folder_url && item.footage_status !== 'READY' && <Button className="ml-auto" size="xs" disabled={running} onClick={() => onClassify(item)}><FolderSearch2 size={11}/>{running ? ' Đang phân loại…' : ' Phân loại footage'}</Button>}
      {item.kind === 'topic' && <Button size="xs" disabled={busy || running} onClick={() => onCreate(item)}>Tạo video</Button>}
      {item.kind === 'job' && item.status === 'APPROVED' && <Button className="ml-auto" size="xs" disabled={busy} onClick={() => onExport(item)}><UploadCloud size={11}/> Xuất Drive</Button>}
      {item.kind === 'job' && item.output_url?.startsWith('https://drive.google.com/') && <a className="ml-auto text-[10px] flex items-center gap-1" style={{ color: 'var(--accent)' }} href={item.output_url} target="_blank" rel="noreferrer"><ExternalLink size={11}/> Mở OUTPUT</a>}
    </div>
    {run && run.status !== 'IDLE' && <div className="ml-5 flex flex-col gap-1.5">
      <div className="flex items-center gap-2 text-[10px]"><span style={{ color: run.status === 'FAILED' ? 'var(--red)' : 'var(--accent)' }}>{run.message}</span><span className="ml-auto" style={{ color: 'var(--muted)' }}>{run.total ? `${run.current}/${run.total} · ${percent}%` : run.stage}</span></div>
      <div className="h-1 rounded overflow-hidden" style={{ background: 'var(--border)' }}><div className="h-full transition-all" style={{ width: `${run.status === 'COMPLETED' ? 100 : percent}%`, background: run.status === 'FAILED' ? 'var(--red)' : 'var(--accent)' }}/></div>
      <details className="text-[9px]" open={run.status === 'FAILED'}><summary className="cursor-pointer" style={{ color: 'var(--muted)' }}>Nhật ký phân loại ({run.logs.length})</summary><div className="mt-1 max-h-32 overflow-auto rounded p-2 flex flex-col gap-1" style={{ background: 'var(--bg)' }}>{run.logs.map((log, index) => <div key={`${log.time}-${index}`}><span style={{ color: 'var(--muted)' }}>{new Date(log.time).toLocaleTimeString()} · {log.stage}</span> — {log.message}</div>)}</div></details>
    </div>}
  </div>
}

export default function PostManagementPage() {
  const [items, setItems] = useState<ContentItem[]>([])
  const [busy, setBusy] = useState(false)
  const [classificationRuns, setClassificationRuns] = useState<Record<string, ClassificationRun>>({})
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    try { setItems(await fetchAPI<ContentItem[]>('/api/production-calendar')); setError(null) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }, [])
  useEffect(() => { void load() }, [load])
  const groups = useMemo(() => ({
    planned: items.filter(x => x.kind === 'topic'),
    working: items.filter(x => x.kind === 'job' && !DONE.has(x.status)),
    done: items.filter(x => x.kind === 'job' && DONE.has(x.status)),
  }), [items])
  async function create(item: ContentItem) {
    setBusy(true)
    try { await fetchAPI('/api/production-jobs', { method: 'POST', body: JSON.stringify({ profile_id: item.profile_id, video_topic_id: item.topic_id }) }); await load() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  async function sync() {
    setBusy(true)
    try { await fetchAPI('/api/profiles/sync-all', { method: 'POST' }); await load() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  async function exportToDrive(item: ContentItem) {
    setBusy(true)
    try { await fetchAPI(`/api/production-jobs/${item.id}/export`, { method: 'POST' }); await load() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  async function classifyFootage(item: ContentItem) {
    try {
      const initial = await fetchAPI<ClassificationRun>(`/api/video-topics/${item.id}/classify-footage`, { method: 'POST' })
      setClassificationRuns(previous => ({ ...previous, [item.id]: initial })); setError(null)
      await pollClassification(item.id)
    }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  async function pollClassification(topicId: string) {
    for (;;) {
      const run = await fetchAPI<ClassificationRun>(`/api/video-topics/${topicId}/classification-status`)
      setClassificationRuns(previous => ({ ...previous, [topicId]: run }))
      if (run.status === 'COMPLETED' || run.status === 'FAILED' || run.status === 'IDLE') { await load(); return }
      await new Promise(resolve => window.setTimeout(resolve, 1500))
    }
  }
  const panels = [
    ['planned', 'Sẽ tạo', groups.planned, Clock3],
    ['working', 'Đang làm', groups.working, LoaderCircle],
    ['done', 'Đã hoàn thành', groups.done, CheckCircle2],
  ] as const
  return <div className="flex flex-col gap-4">
    <div className="flex items-center"><div><h1 className="m-0 text-lg font-semibold">Quản lý video</h1><p className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>Theo dõi toàn bộ video sẽ tạo, đang sản xuất và đã hoàn thành.</p></div><Button className="ml-auto" size="sm" disabled={busy} onClick={sync}><RefreshCw size={12} className={busy ? 'animate-spin' : undefined}/> Đồng bộ</Button></div>
    {error && <div className="text-xs" style={{ color: 'var(--red)' }}>{error}</div>}
    <Tabs defaultValue="planned">
      <TabsList>{panels.map(([key,label,list]) => <TabsTrigger key={key} value={key}>{label} ({list.length})</TabsTrigger>)}</TabsList>
      {panels.map(([key,,list,Icon]) => <TabsContent key={key} value={key}><Card className="py-4"><CardContent className="flex flex-col gap-2">{list.length ? list.map(item => <ItemRow key={`${item.kind}-${item.id}`} item={item} busy={busy} run={classificationRuns[item.id]} onCreate={create} onExport={exportToDrive} onClassify={classifyFootage}/>) : <div className="py-8 text-center text-xs" style={{color:'var(--muted)'}}><Icon size={18} className="mx-auto mb-2"/>Không có video trong nhóm này.</div>}</CardContent></Card></TabsContent>)}
    </Tabs>
  </div>
}
