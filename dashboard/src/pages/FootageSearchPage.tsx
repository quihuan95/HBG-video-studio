import { useEffect, useState } from 'react'
import { Download, Search, Sparkles } from 'lucide-react'
import { fetchAPI } from '../api/client'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'

type Profile = { id: string; name: string }
type Candidate = { id: string; provider: string; title: string; source_url: string; preview_url?: string; thumbnail_url?: string; duration_s?: number; fit_score?: number; timestamp_status: string; license_status: string; verification_status: string; selected: number }
type Shot = { id: string; order_index: number; script_excerpt: string; visual_description: string; timeline_start_s: number; timeline_end_s: number; keywords_vi: string[]; keywords_en: string[]; candidates: Candidate[] }
type Job = { id: string; status: string; provider_status: Record<string,string>; shots: Shot[] }

const field = 'w-full rounded px-2 py-2 text-xs outline-none'
const style = { background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)' }
const apiBase = () => import.meta.env.DEV ? '' : 'http://127.0.0.1:8100'

export default function FootageSearchPage() {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [profileId, setProfileId] = useState('')
  const [script, setScript] = useState('')
  const [duration, setDuration] = useState(60)
  const [ratio, setRatio] = useState('9:16')
  const [preference, setPreference] = useState('internal_first')
  const [job, setJob] = useState<Job | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  useEffect(() => { fetchAPI<Profile[]>('/api/profiles').then(setProfiles).catch(e => setError(String(e))) }, [])
  useEffect(() => {
    const query = new URLSearchParams(window.location.hash.split('?')[1] || window.location.search)
    const existing = query.get('job')
    if (existing) fetchAPI<Job>(`/api/footage-research/jobs/${existing}`).then(setJob).catch(e => setError(String(e)))
  }, [])
  useEffect(() => {
    if (!job || job.status !== 'SEARCHING') return
    const timer = setInterval(() => fetchAPI<Job>(`/api/footage-research/jobs/${job.id}`).then(setJob).catch(() => {}), 1500)
    return () => clearInterval(timer)
  }, [job?.id, job?.status])

  async function analyze() {
    setBusy('analyze'); setError('')
    try {
      const created = await fetchAPI<{id:string}>('/api/footage-research/jobs', { method: 'POST', body: JSON.stringify({ profile_id: profileId || null, script_text: script, target_duration_seconds: duration, aspect_ratio: ratio, source_preference: preference }) })
      setJob(await fetchAPI<Job>(`/api/footage-research/jobs/${created.id}/analyze`, { method: 'POST' }))
    } catch (e) { setError(String(e)) } finally { setBusy('') }
  }
  async function search() {
    if (!job) return; setBusy('search'); setError('')
    try { await fetchAPI(`/api/footage-research/jobs/${job.id}/search`, { method: 'POST' }); setJob({ ...job, status: 'SEARCHING' }) }
    catch (e) { setError(String(e)) } finally { setBusy('') }
  }
  async function select(shot: Shot, candidate: Candidate) {
    await fetchAPI(`/api/footage-research/shots/${shot.id}/selection`, { method: 'PATCH', body: JSON.stringify({ candidate_id: candidate.id }) })
    if (job) setJob(await fetchAPI<Job>(`/api/footage-research/jobs/${job.id}`))
  }
  function download(path: string) { window.open(`${apiBase()}${path}`, '_blank') }

  return <div className="flex flex-col gap-4">
    <div><h1 className="m-0 text-lg font-semibold">AI Footage Search</h1><p className="mt-1 text-[11px]" style={{color:'var(--muted)'}}>Tách kịch bản thành shot, tìm trong kho local/Drive và nguồn stock online, rồi xuất shotlist hoặc media package cho CapCut.</p></div>
    {error && <div className="rounded p-3 text-xs" style={{background:'var(--card)',color:'var(--red)'}}>{error}</div>}
    <Card><CardHeader><CardTitle className="text-xs">KỊCH BẢN / VOICE-OVER</CardTitle></CardHeader><CardContent className="flex flex-col gap-3">
      <textarea rows={7} className={field} style={style} value={script} onChange={e=>setScript(e.target.value)} placeholder="Dán kịch bản hoặc voice-over tiếng Việt..." />
      <div className="grid grid-cols-4 gap-3">
        <label className="text-[9px]">PROFILE<select className={field} style={style} value={profileId} onChange={e=>setProfileId(e.target.value)}><option value="">Không giới hạn profile</option>{profiles.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        <label className="text-[9px]">THỜI LƯỢNG<input className={field} style={style} type="number" min={5} max={600} value={duration} onChange={e=>setDuration(Number(e.target.value))}/></label>
        <label className="text-[9px]">TỶ LỆ<select className={field} style={style} value={ratio} onChange={e=>setRatio(e.target.value)}><option>9:16</option><option>16:9</option><option>1:1</option></select></label>
        <label className="text-[9px]">ƯU TIÊN<select className={field} style={style} value={preference} onChange={e=>setPreference(e.target.value)}><option value="internal_first">Internal first</option><option value="mixed">Mixed</option><option value="external_only">External only</option></select></label>
      </div>
      <div className="flex gap-2"><Button disabled={!script.trim() || !!busy} onClick={analyze}><Sparkles/> {busy==='analyze'?'Đang phân tích...':'Phân tích kịch bản'}</Button>{job && job.shots.length > 0 && <Button disabled={!!busy||job.status==='SEARCHING'} onClick={search}><Search/> {job.status==='SEARCHING'?'Worker đang tìm...':'Tìm footage'}</Button>}</div>
    </CardContent></Card>
    {job && <div className="flex items-center gap-2 text-[10px]"><Badge>{job.status}</Badge>{Object.entries(job.provider_status||{}).map(([key,value])=><Badge key={key} variant="outline">{key}: {value}</Badge>)}<span className="ml-auto"/>{job.status==='READY'&&<><Button size="xs" variant="outline" onClick={()=>download(`/api/footage-research/jobs/${job.id}/export?format=csv`)}><Download/> CSV</Button><Button size="xs" variant="outline" onClick={()=>download(`/api/footage-research/jobs/${job.id}/export?format=json`)}><Download/> JSON</Button><Button size="xs" onClick={()=>download(`/api/footage-research/jobs/${job.id}/export-media`)}><Download/> Gói CapCut</Button></>}</div>}
    {job?.shots?.map(shot=><Card key={shot.id}><CardHeader><CardTitle className="text-xs">SHOT {shot.order_index} · {shot.timeline_start_s.toFixed(1)}–{shot.timeline_end_s.toFixed(1)}s</CardTitle></CardHeader><CardContent><div className="text-xs">{shot.script_excerpt}</div><div className="mt-1 text-[10px]" style={{color:'var(--muted)'}}>{shot.visual_description}</div><div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">{shot.candidates?.map(c=><div key={c.id} className="rounded border p-2" style={{borderColor:c.selected?'var(--accent)':'var(--border)',background:'var(--background)'}}>{c.thumbnail_url&&<img src={c.thumbnail_url} className="mb-2 h-28 w-full rounded object-cover"/>}<div className="truncate text-xs font-medium">{c.title}</div><div className="mt-1 flex flex-wrap gap-1"><Badge variant="outline">{c.provider}</Badge><Badge variant="outline">FIT {Math.round(c.fit_score||0)}</Badge><Badge variant="outline">TIME {c.timestamp_status}</Badge><Badge variant="outline">LICENSE {c.license_status}</Badge></div><div className="mt-2 flex gap-2"><a href={c.source_url} target="_blank" rel="noreferrer" className="text-[10px] underline">Mở source</a>{c.preview_url&&<a href={c.preview_url} target="_blank" rel="noreferrer" className="text-[10px] underline">Preview</a>}<Button className="ml-auto" size="xs" variant={c.selected?'default':'outline'} onClick={()=>select(shot,c)}>{c.selected?'Đã chọn':'Chọn'}</Button></div></div>)}</div>{job.status==='READY'&&shot.candidates.length===0&&<div className="mt-3 text-xs" style={{color:'var(--muted)'}}>Không tìm thấy source phù hợp; cần editor kiểm tra thủ công.</div>}</CardContent></Card>)}
  </div>
}
