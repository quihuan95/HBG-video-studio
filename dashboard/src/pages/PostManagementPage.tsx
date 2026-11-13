import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Clock3, ExternalLink, LoaderCircle, RefreshCw, RotateCcw, Trash2, UploadCloud, XCircle } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
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
  capcut_draft_path?: string | null
  capcut_error?: string | null
  footage_mode?: FootageMode | null
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

type FootageMode = 'DRIVE_ONLY' | 'INTERNET_ONLY' | 'HYBRID'

const DONE = new Set(['MANUALLY_UPLOADED', 'COMPLETED', 'ARCHIVED', 'READY_FOR_MANUAL_UPLOAD'])
const TERMINAL = new Set([...DONE, 'CANCELLED'])

function ItemRow({ item, busy, capcutBusy, productionRun, onCreate, onRegenerate, onExport, onCancel, onDelete, onOpenCapCut, onRegenerateCapCut }: { item: ContentItem; busy: boolean; capcutBusy: boolean; productionRun?: ProductionRun; onCreate: (item: ContentItem, mode: FootageMode) => void; onRegenerate: (item: ContentItem) => void; onExport: (item: ContentItem) => void; onCancel: (item: ContentItem) => void; onDelete: (item: ContentItem) => void; onOpenCapCut: (item: ContentItem) => void; onRegenerateCapCut: (item: ContentItem) => void }) {
  const [footageMode, setFootageMode] = useState<FootageMode>('HYBRID')
  return <div className="flex flex-col gap-2 px-3 py-2.5 rounded border" style={{ borderColor: 'var(--border)' }}>
    <div className="flex items-center gap-3">
      <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: item.color }} />
      <div className="flex flex-col min-w-0">
        <span className="text-xs truncate">{item.topic_title || 'Video không gắn tab nguồn'}</span>
        <span className="text-[9px]" style={{ color: 'var(--muted)' }}>{item.profile_name} · {item.date} {item.time} · {item.kind === 'topic' ? 'FOOTAGE: CHỌN KHI TẠO' : `${item.status} · ${item.footage_mode || 'HYBRID'}`}</span>
      </div>
      {item.kind === 'topic' && <><select className="ml-auto rounded border bg-transparent px-2 py-1 text-[10px]" style={{ borderColor: 'var(--border)' }} value={footageMode} onChange={event => setFootageMode(event.target.value as FootageMode)} disabled={busy}><option value="DRIVE_ONLY">100% Drive</option><option value="INTERNET_ONLY">100% Internet</option><option value="HYBRID">Drive + Internet</option></select><Button size="xs" disabled={busy} title="Tạo voice trước, sau đó tìm footage theo nguồn đã chọn" onClick={() => onCreate(item, footageMode)}>Tạo video</Button></>}
      {item.kind === 'job' && item.status === 'APPROVED' && <Button className="ml-auto" size="xs" disabled={busy} onClick={() => onExport(item)}><UploadCloud size={11}/> Xuất Drive</Button>}
      {item.kind === 'job' && item.output_url?.startsWith('https://drive.google.com/') && <a className="ml-auto text-[10px] flex items-center gap-1" style={{ color: 'var(--accent)' }} href={item.output_url} target="_blank" rel="noreferrer"><ExternalLink size={11}/> Mở OUTPUT</a>}
      {item.kind === 'job' && item.capcut_draft_path && <Button className={item.output_url ? '' : 'ml-auto'} size="xs" variant="outline" disabled={busy} onClick={() => onOpenCapCut(item)}>Mở CapCut</Button>}
      {item.kind === 'job' && DONE.has(item.status) && <Button size="xs" variant="outline" disabled={busy || capcutBusy} onClick={() => onRegenerateCapCut(item)}><RotateCcw size={11} className={capcutBusy ? 'animate-spin' : undefined}/> {capcutBusy ? 'Đang tạo draft…' : item.capcut_draft_path ? 'Tạo lại draft' : 'Tạo draft CapCut'}</Button>}
      {item.kind === 'job' && TERMINAL.has(item.status) && item.status !== 'ARCHIVED' && <Button className={item.output_url ? '' : 'ml-auto'} size="xs" variant="outline" disabled={busy} onClick={() => onRegenerate(item)}><RotateCcw size={11}/> Tạo lại</Button>}
      {item.kind === 'job' && TERMINAL.has(item.status) && <Button size="xs" variant="destructive" disabled={busy} onClick={() => onDelete(item)}><Trash2 size={11}/> Xóa video</Button>}
      {item.kind === 'job' && !TERMINAL.has(item.status) && <Button className={item.status === 'APPROVED' ? '' : 'ml-auto'} size="xs" variant="destructive" disabled={busy} onClick={() => onCancel(item)}><XCircle size={11}/> Hủy làm video</Button>}
    </div>
    {item.kind === 'job' && productionRun && <div className="ml-5 flex flex-col gap-2">
      <div className="flex items-center text-[10px]"><span style={{ color: ['FAILED','CANCELLED'].includes(productionRun.status) ? 'var(--red)' : 'var(--accent)' }}>{productionRun.message}</span><span className="ml-auto" style={{ color: 'var(--muted)' }}>{productionRun.percent}% · {productionRun.stage}</span></div>
      <div className="h-1 rounded overflow-hidden" style={{ background: 'var(--border)' }}><div className="h-full transition-all" style={{ width: `${productionRun.percent}%`, background: productionRun.status === 'FAILED' ? 'var(--red)' : 'var(--accent)' }}/></div>
      <div className="grid grid-cols-4 gap-1">{productionRun.stages.map(stage => <div key={stage.key} className="rounded px-2 py-1 text-[8px] truncate" title={stage.name} style={{ background: 'var(--bg)', color: stage.status === 'COMPLETED' ? 'var(--green)' : stage.status === 'PROCESSING' ? 'var(--accent)' : ['FAILED','CANCELLED'].includes(stage.status) ? 'var(--red)' : 'var(--muted)', border: '1px solid var(--border)' }}>{stage.status === 'COMPLETED' ? '✓' : stage.status === 'PROCESSING' ? '●' : stage.status === 'CANCELLED' ? '×' : '○'} {stage.name}</div>)}</div>
      <details className="text-[9px]" open={productionRun.status === 'FAILED'}><summary className="cursor-pointer" style={{ color: 'var(--muted)' }}>Nhật ký sản xuất ({productionRun.logs.length})</summary><div className="mt-1 max-h-32 overflow-auto rounded p-2 flex flex-col gap-1" style={{ background: 'var(--bg)' }}>{productionRun.logs.map((log, index) => <div key={`${log.time}-${index}`}><span style={{ color: 'var(--muted)' }}>{new Date(log.time).toLocaleTimeString()} · {log.stage}</span> — {log.message}</div>)}</div></details>
    </div>}
  </div>
}

export default function PostManagementPage({ view = 'create' }: { view?: 'create' | 'created' }) {
  const navigate = useNavigate()
  const [items, setItems] = useState<ContentItem[]>([])
  const [busy, setBusy] = useState(false)
  const [capcutBusyId, setCapcutBusyId] = useState<string | null>(null)
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
  async function create(item: ContentItem, footageMode: FootageMode) {
    setBusy(true)
    try { await fetchAPI('/api/production-jobs', { method: 'POST', body: JSON.stringify({ profile_id: item.profile_id, video_topic_id: item.topic_id, footage_mode: footageMode }) }); await load() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  async function regenerate(item: ContentItem) {
    if (!window.confirm(`Tạo lại video "${item.topic_title || item.id}"? Bản đã xuất trước đó vẫn được giữ trong lịch sử.`)) return
    setBusy(true)
    try { await fetchAPI(`/api/production-jobs/${item.id}/regenerate`, { method: 'POST' }); await load(); setError(null) }
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
  async function deleteVideo(item: ContentItem) {
    const driveNote = item.output_url ? '\nFile đã xuất trên Google Drive sẽ được giữ nguyên.' : ''
    if (!window.confirm(`Xóa video "${item.topic_title || item.id}"? Video sẽ quay về mục Tạo video.${driveNote}`)) return
    setBusy(true)
    try {
      await fetchAPI(`/api/production-jobs/${item.id}`, { method: 'DELETE' })
      setError(null)
      navigate('/')
      await load()
    }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  async function openCapCut(item: ContentItem) {
    try { await fetchAPI(`/api/production-jobs/${item.id}/open-capcut`, { method: 'POST' }); setError(null) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  async function regenerateCapCut(item: ContentItem) {
    if (!window.confirm(`${item.capcut_draft_path ? 'Tạo lại' : 'Tạo'} draft CapCut cho "${item.topic_title || item.id}"? Hãy đóng CapCut trước khi tiếp tục.`)) return
    setCapcutBusyId(item.id)
    try { await fetchAPI(`/api/production-jobs/${item.id}/regenerate-capcut`, { method: 'POST' }); await load(); setError(null) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setCapcutBusyId(null) }
  }
  const createdSections = [
    ['Đang làm', groups.working, LoaderCircle],
    ['Đã hoàn thành', groups.done, CheckCircle2],
    ['Đã hủy', groups.cancelled, XCircle],
  ] as const
  return <div className="flex flex-col gap-4">
    <div className="flex items-center"><div><h1 className="m-0 text-lg font-semibold">{view === 'create' ? 'Tạo video' : 'Video đã tạo'}</h1><p className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>{view === 'create' ? 'Tạo kịch bản và voice trước, sau đó tìm footage từ Drive, Internet hoặc cả hai.' : 'Theo dõi video đang sản xuất, đã hoàn thành hoặc đã hủy.'}</p></div><Button className="ml-auto" size="sm" disabled={busy} onClick={sync}><RefreshCw size={12} className={busy ? 'animate-spin' : undefined}/> Đồng bộ</Button></div>
    {error && <div className="text-xs" style={{ color: 'var(--red)' }}>{error}</div>}
    {view === 'create' ? <VideoSection title={`Sẽ tạo (${groups.planned.length})`} items={groups.planned} empty="Không có video đang chờ tạo." icon={Clock3} busy={busy} capcutBusyId={capcutBusyId} productionRuns={productionRuns} onCreate={create} onRegenerate={regenerate} onExport={exportToDrive} onCancel={cancelProduction} onDelete={deleteVideo} onOpenCapCut={openCapCut} onRegenerateCapCut={regenerateCapCut}/> : createdSections.map(([title, list, Icon]) => <VideoSection key={title} title={`${title} (${list.length})`} items={list} empty={`Không có video trong mục ${title.toLowerCase()}.`} icon={Icon} busy={busy} capcutBusyId={capcutBusyId} productionRuns={productionRuns} onCreate={create} onRegenerate={regenerate} onExport={exportToDrive} onCancel={cancelProduction} onDelete={deleteVideo} onOpenCapCut={openCapCut} onRegenerateCapCut={regenerateCapCut}/>) }
  </div>
}

function VideoSection({ title, items, empty, icon: Icon, busy, capcutBusyId, productionRuns, onCreate, onRegenerate, onExport, onCancel, onDelete, onOpenCapCut, onRegenerateCapCut }: {
  title: string; items: ContentItem[]; empty: string; icon: typeof Clock3; busy: boolean; capcutBusyId: string | null
  productionRuns: Record<string, ProductionRun>
  onCreate: (item: ContentItem, mode: FootageMode) => void; onRegenerate: (item: ContentItem) => void; onExport: (item: ContentItem) => void
  onCancel: (item: ContentItem) => void; onDelete: (item: ContentItem) => void; onOpenCapCut: (item: ContentItem) => void; onRegenerateCapCut: (item: ContentItem) => void
}) {
  return <Card className="py-4"><CardContent className="flex flex-col gap-2">
    <div className="text-[10px] font-semibold uppercase tracking-wide flex items-center gap-2 mb-1" style={{ color: 'var(--muted)' }}><Icon size={13}/>{title}</div>
    {items.length ? items.map(item => <ItemRow key={`${item.kind}-${item.id}`} item={item} busy={busy} capcutBusy={capcutBusyId === item.id} productionRun={productionRuns[item.id]} onCreate={onCreate} onRegenerate={onRegenerate} onExport={onExport} onCancel={onCancel} onDelete={onDelete} onOpenCapCut={onOpenCapCut} onRegenerateCapCut={onRegenerateCapCut}/>) : <div className="py-8 text-center text-xs" style={{color:'var(--muted)'}}><Icon size={18} className="mx-auto mb-2"/>{empty}</div>}
  </CardContent></Card>
}
