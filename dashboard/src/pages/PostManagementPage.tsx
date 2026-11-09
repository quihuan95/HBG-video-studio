import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Clock3, ExternalLink, FolderSearch2, LoaderCircle, RefreshCw, UploadCloud, XCircle } from 'lucide-react'
import { fetchAPI } from '../api/client'
import { Button } from '../components/ui/button'
import { Card, CardContent } from '../components/ui/card'

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
  footage_result?: { classified_folder_url?: string } | null
}

interface ClassificationRun {
  video_topic_id: string
  status: 'IDLE' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  stage: string
  message: string
  current: number
  total: number
  logs: { time: string; stage: string; message: string }[]
  result?: { organization?: { classified_folder_url?: string } }
}

interface ProductionRun {
  production_job_id: string
  status: string
  stage: string
  message: string
  percent: number
  stages: { key: string; name: string; status: string }[]
  logs: { time: string; stage: string; message: string }[]
  error?: string | null
}

const DONE = new Set(['MANUALLY_UPLOADED', 'COMPLETED', 'ARCHIVED', 'READY_FOR_MANUAL_UPLOAD'])
const TERMINAL = new Set([...DONE, 'CANCELLED'])

function ItemRow({ item, busy, run, productionRun, onCreate, onExport, onClassify, onCancel }: { item: ContentItem; busy: boolean; run?: ClassificationRun; productionRun?: ProductionRun; onCreate: (item: ContentItem) => void; onExport: (item: ContentItem) => void; onClassify: (item: ContentItem) => void; onCancel: (item: ContentItem) => void }) {
  const running = run?.status === 'RUNNING'
  const percent = run?.total ? Math.round((run.current / run.total) * 100) : 0
  return <div className="flex flex-col gap-2 px-3 py-2.5 rounded border" style={{ borderColor: 'var(--border)' }}>
    <div className="flex items-center gap-3">
      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: item.color }} />
      <div className="flex flex-col min-w-0">
        <span className="text-xs truncate">{item.topic_title || 'Video không gắn tab nguồn'}</span>
        <span className="text-[9px]" style={{ color: 'var(--muted)' }}>{item.profile_name} · {item.date} {item.time} · {item.kind === 'topic' ? `FOOTAGE: ${running ? run.stage : item.footage_status || 'PENDING'}` : item.status}</span>
      </div>
      {item.kind === 'topic' && item.footage_folder_url && <Button className="ml-auto" size="xs" variant={item.footage_status === 'READY' ? 'outline' : 'default'} disabled={running} onClick={() => onClassify(item)}><FolderSearch2 size={11}/>{running ? ' Đang phân loại…' : item.footage_status === 'READY' ? ' Phân tích lại' : ' Phân loại footage'}</Button>}
      {item.kind === 'topic' && <Button size="xs" disabled={busy || running || item.footage_status !== 'READY'} title={item.footage_status === 'READY' ? 'Tạo video' : 'Phải phân loại footage thành công trước'} onClick={() => onCreate(item)}>{item.footage_status === 'READY' ? 'Tạo video' : 'Chờ footage'}</Button>}
      {item.kind === 'job' && item.status === 'APPROVED' && <Button className="ml-auto" size="xs" disabled={busy} onClick={() => onExport(item)}><UploadCloud size={11}/> Xuất Drive</Button>}
      {item.kind === 'job' && item.output_url?.startsWith('https://drive.google.com/') && <a className="ml-auto text-[10px] flex items-center gap-1" style={{ color: 'var(--accent)' }} href={item.output_url} target="_blank" rel="noreferrer"><ExternalLink size={11}/> Mở OUTPUT</a>}
      {item.kind === 'job' && !TERMINAL.has(item.status) && <Button className={item.status === 'APPROVED' ? '' : 'ml-auto'} size="xs" variant="destructive" disabled={busy} onClick={() => onCancel(item)}><XCircle size={11}/> Hủy làm video</Button>}
    </div>
    {run && run.status !== 'IDLE' && <div className="ml-5 flex flex-col gap-1.5">
      <div className="flex items-center gap-2 text-[10px]"><span style={{ color: run.status === 'FAILED' ? 'var(--red)' : 'var(--accent)' }}>{run.message}</span><span className="ml-auto" style={{ color: 'var(--muted)' }}>{run.total ? `${run.current}/${run.total} · ${percent}%` : run.stage}</span></div>
      <div className="h-1 rounded overflow-hidden" style={{ background: 'var(--border)' }}><div className="h-full transition-all" style={{ width: `${run.status === 'COMPLETED' ? 100 : percent}%`, background: run.status === 'FAILED' ? 'var(--red)' : 'var(--accent)' }}/></div>
      <details className="text-[9px]" open={run.status === 'FAILED'}><summary className="cursor-pointer" style={{ color: 'var(--muted)' }}>Nhật ký phân loại ({run.logs.length})</summary><div className="mt-1 max-h-32 overflow-auto rounded p-2 flex flex-col gap-1" style={{ background: 'var(--bg)' }}>{run.logs.map((log, index) => <div key={`${log.time}-${index}`}><span style={{ color: 'var(--muted)' }}>{new Date(log.time).toLocaleTimeString()} · {log.stage}</span> — {log.message}</div>)}</div></details>
    </div>}
    {(run?.result?.organization?.classified_folder_url || item.footage_result?.classified_folder_url) && <a className="ml-5 text-[10px] flex items-center gap-1 w-fit" style={{ color: 'var(--accent)' }} href={run?.result?.organization?.classified_folder_url || item.footage_result?.classified_folder_url} target="_blank" rel="noreferrer"><ExternalLink size={11}/> Mở kết quả phân loại trên Drive</a>}
    {item.kind === 'job' && productionRun && <div className="ml-5 flex flex-col gap-2">
      <div className="flex items-center text-[10px]"><span style={{ color: ['FAILED','CANCELLED'].includes(productionRun.status) ? 'var(--red)' : 'var(--accent)' }}>{productionRun.message}</span><span className="ml-auto" style={{ color: 'var(--muted)' }}>{productionRun.percent}% · {productionRun.stage}</span></div>
      <div className="h-1 rounded overflow-hidden" style={{ background: 'var(--border)' }}><div className="h-full transition-all" style={{ width: `${productionRun.percent}%`, background: productionRun.status === 'FAILED' ? 'var(--red)' : 'var(--accent)' }}/></div>
      <div className="grid grid-cols-4 gap-1">{productionRun.stages.map(stage => <div key={stage.key} className="rounded px-2 py-1 text-[8px] truncate" title={stage.name} style={{ background: 'var(--bg)', color: stage.status === 'COMPLETED' ? 'var(--green)' : stage.status === 'PROCESSING' ? 'var(--accent)' : ['FAILED','CANCELLED'].includes(stage.status) ? 'var(--red)' : 'var(--muted)', border: '1px solid var(--border)' }}>{stage.status === 'COMPLETED' ? '✓' : stage.status === 'PROCESSING' ? '●' : stage.status === 'CANCELLED' ? '×' : '○'} {stage.name}</div>)}</div>
      <details className="text-[9px]" open={productionRun.status === 'FAILED'}><summary className="cursor-pointer" style={{ color: 'var(--muted)' }}>Nhật ký sản xuất ({productionRun.logs.length})</summary><div className="mt-1 max-h-32 overflow-auto rounded p-2 flex flex-col gap-1" style={{ background: 'var(--bg)' }}>{productionRun.logs.map((log, index) => <div key={`${log.time}-${index}`}><span style={{ color: 'var(--muted)' }}>{new Date(log.time).toLocaleTimeString()} · {log.stage}</span> — {log.message}</div>)}</div></details>
    </div>}
  </div>
}

export default function PostManagementPage({ view = 'create' }: { view?: 'create' | 'created' }) {
  const [items, setItems] = useState<ContentItem[]>([])
  const [busy, setBusy] = useState(false)
  const [classificationRuns, setClassificationRuns] = useState<Record<string, ClassificationRun>>({})
  const [productionRuns, setProductionRuns] = useState<Record<string, ProductionRun>>({})
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    try {
      const rows = await fetchAPI<ContentItem[]>('/api/production-calendar'); setItems(rows)
      const jobs = rows.filter(item => item.kind === 'job')
      const progress = await Promise.all(jobs.map(async item => {
        try { return await fetchAPI<ProductionRun>(`/api/production-jobs/${item.id}/progress`) }
        catch { return null }
      }))
      setProductionRuns(Object.fromEntries(progress.filter((run): run is ProductionRun => Boolean(run)).map(run => [run.production_job_id, run])))
      setError(null)
    }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }, [])
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 3000); return () => window.clearInterval(timer) }, [load])
  const groups = useMemo(() => ({
    planned: items.filter(x => x.kind === 'topic'),
    working: items.filter(x => x.kind === 'job' && !TERMINAL.has(x.status)),
    done: items.filter(x => x.kind === 'job' && DONE.has(x.status)),
    cancelled: items.filter(x => x.kind === 'job' && x.status === 'CANCELLED'),
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
  async function cancelProduction(item: ContentItem) {
    if (!window.confirm(`Hủy làm video "${item.topic_title || item.id}"?`)) return
    setBusy(true)
    try { await fetchAPI(`/api/production-jobs/${item.id}/cancel`, { method: 'POST' }); await load(); setError(null) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  async function classifyFootage(item: ContentItem) {
    try {
      const force = item.footage_status === 'READY'
      const initial = await fetchAPI<ClassificationRun>(`/api/video-topics/${item.id}/classify-footage?force=${force}`, { method: 'POST' })
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
  const createdSections = [
    ['Đang làm', groups.working, LoaderCircle],
    ['Đã hoàn thành', groups.done, CheckCircle2],
    ['Đã hủy', groups.cancelled, XCircle],
  ] as const
  return <div className="flex flex-col gap-4">
    <div className="flex items-center"><div><h1 className="m-0 text-lg font-semibold">{view === 'create' ? 'Tạo video' : 'Video đã tạo'}</h1><p className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>{view === 'create' ? 'Phân loại footage và bắt đầu tạo video từ kịch bản Sheet.' : 'Theo dõi video đang sản xuất, đã hoàn thành hoặc đã hủy.'}</p></div><Button className="ml-auto" size="sm" disabled={busy} onClick={sync}><RefreshCw size={12} className={busy ? 'animate-spin' : undefined}/> Đồng bộ</Button></div>
    {error && <div className="text-xs" style={{ color: 'var(--red)' }}>{error}</div>}
    {view === 'create' ? <VideoSection title={`Sẽ tạo (${groups.planned.length})`} items={groups.planned} empty="Không có video đang chờ tạo." icon={Clock3} busy={busy} classificationRuns={classificationRuns} productionRuns={productionRuns} onCreate={create} onExport={exportToDrive} onClassify={classifyFootage} onCancel={cancelProduction}/> : createdSections.map(([title, list, Icon]) => <VideoSection key={title} title={`${title} (${list.length})`} items={list} empty={`Không có video trong mục ${title.toLowerCase()}.`} icon={Icon} busy={busy} classificationRuns={classificationRuns} productionRuns={productionRuns} onCreate={create} onExport={exportToDrive} onClassify={classifyFootage} onCancel={cancelProduction}/>) }
  </div>
}

function VideoSection({ title, items, empty, icon: Icon, busy, classificationRuns, productionRuns, onCreate, onExport, onClassify, onCancel }: {
  title: string; items: ContentItem[]; empty: string; icon: typeof Clock3; busy: boolean
  classificationRuns: Record<string, ClassificationRun>; productionRuns: Record<string, ProductionRun>
  onCreate: (item: ContentItem) => void; onExport: (item: ContentItem) => void
  onClassify: (item: ContentItem) => void; onCancel: (item: ContentItem) => void
}) {
  return <Card className="py-4"><CardContent className="flex flex-col gap-2">
    <div className="text-[10px] font-semibold uppercase tracking-wide flex items-center gap-2 mb-1" style={{ color: 'var(--muted)' }}><Icon size={13}/>{title}</div>
    {items.length ? items.map(item => <ItemRow key={`${item.kind}-${item.id}`} item={item} busy={busy} run={classificationRuns[item.id]} productionRun={productionRuns[item.id]} onCreate={onCreate} onExport={onExport} onClassify={onClassify} onCancel={onCancel}/>) : <div className="py-8 text-center text-xs" style={{color:'var(--muted)'}}><Icon size={18} className="mx-auto mb-2"/>{empty}</div>}
  </CardContent></Card>
}
