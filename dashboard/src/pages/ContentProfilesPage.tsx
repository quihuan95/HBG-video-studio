import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, RefreshCw } from 'lucide-react'
import { fetchAPI } from '../api/client'
import { Badge } from '../components/ui/badge'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'

interface Profile { id: string; name: string; workflow_mode: string; timezone: string; default_time: string; sheet_id_topics?: string; folder_id_rules?: string; folder_id_output?: string; voice_provider: string; voice_id: string; color: string; active: boolean }
interface RuleVersion { id: string; version: number; content: string; content_hash: string; publish_config_json: string; status: string; created_at: string }

const inputClass = 'text-xs px-2 py-1.5 rounded outline-none w-full'
const inputStyle = { background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)' }
const formatDate = (value: string) => new Intl.DateTimeFormat('vi-VN', { dateStyle: 'short', timeStyle: 'short' }).format(new Date(value))

function RuleViewer({ profileId, refreshKey }: { profileId: string; refreshKey: number }) {
  const [rules, setRules] = useState<RuleVersion[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const loadRules = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchAPI<RuleVersion[]>(`/api/profiles/${profileId}/rules`)
      setRules(data)
      setSelectedId(current => data.some(rule => rule.id === current) ? current : data[0]?.id ?? null)
      setError(null)
    } catch (e) { setError(String(e)) }
    finally { setLoading(false) }
  }, [profileId])
  useEffect(() => { void loadRules() }, [loadRules, refreshKey])
  const selected = rules.find(rule => rule.id === selectedId)
  let publishConfig: unknown = null
  if (selected?.publish_config_json && selected.publish_config_json !== '{}') {
    try { publishConfig = JSON.parse(selected.publish_config_json) } catch { publishConfig = selected.publish_config_json }
  }

  return <div className="border-t px-4 py-3" style={{ borderColor: 'var(--border)' }}>
    <div className="mb-3 flex items-center justify-between"><div><div className="text-xs font-medium">Rule đã đồng bộ</div><div className="text-[9px]" style={{ color: 'var(--muted)' }}>Phiên bản mới nhất được dùng cho các video tạo sau thời điểm đồng bộ.</div></div><Button size="xs" variant="outline" disabled={loading} onClick={() => void loadRules()}><RefreshCw className={loading ? 'animate-spin' : ''}/> Làm mới</Button></div>
    {error && <div className="text-xs" style={{ color: 'var(--red)' }}>{error}</div>}
    {!error && loading && <div className="text-xs" style={{ color: 'var(--muted)' }}>Đang tải rule...</div>}
    {!error && !loading && rules.length === 0 && <div className="rounded p-3 text-xs" style={{ background: 'var(--background)', color: 'var(--muted)' }}>Profile này chưa có rule nào được đồng bộ.</div>}
    {rules.length > 0 && <div className="grid gap-3 md:grid-cols-[180px_minmax(0,1fr)]"><div className="flex flex-col gap-1">{rules.map((rule, index) => <button key={rule.id} type="button" onClick={() => setSelectedId(rule.id)} className="rounded px-2 py-2 text-left text-[10px]" style={{ background: selectedId === rule.id ? 'var(--accent)' : 'var(--background)', color: 'var(--text)' }}><div className="flex items-center justify-between"><span className="font-medium">Phiên bản {rule.version}</span>{index === 0 && <Badge variant="secondary">Mới nhất</Badge>}</div><div className="mt-1" style={{ color: 'var(--muted)' }}>{formatDate(rule.created_at)}</div></button>)}</div>
      {selected && <div className="min-w-0"><div className="mb-2 flex flex-wrap items-center gap-2 text-[9px]" style={{ color: 'var(--muted)' }}><Badge variant="outline">{selected.status}</Badge><span>Hash: {selected.content_hash.slice(0, 12)}…</span></div><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded p-3 text-[11px] leading-5" style={{ background: 'var(--background)', color: 'var(--text)', border: '1px solid var(--border)' }}>{selected.content}</pre>{publishConfig !== null && <details className="mt-2 text-[10px]"><summary className="cursor-pointer" style={{ color: 'var(--muted)' }}>Cấu hình publish</summary><pre className="mt-1 overflow-auto rounded p-2" style={{ background: 'var(--background)' }}>{typeof publishConfig === 'string' ? publishConfig : JSON.stringify(publishConfig, null, 2)}</pre></details>}</div>}
    </div>}
  </div>
}

export default function ContentProfilesPage() {
  const emptyForm = { name: '', sheet_id_topics: '', folder_id_rules: '', folder_id_output: '', workflow_mode: 'semi_auto', timezone: 'Asia/Ho_Chi_Minh', default_time: '09:00', voice_provider: 'openai', voice_id: 'marin', color: '#22c55e' }
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [form, setForm] = useState(emptyForm)
  const [editId, setEditId] = useState<string | null>(null)
  const [openRuleProfileId, setOpenRuleProfileId] = useState<string | null>(null)
  const [syncingId, setSyncingId] = useState<string | null>(null)
  const [ruleRefresh, setRuleRefresh] = useState<Record<string, number>>({})
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => fetchAPI<Profile[]>('/api/profiles').then(setProfiles).catch(e => setError(String(e))), [])
  useEffect(() => { void load() }, [load])
  function resetForm() { setEditId(null); setForm(emptyForm) }
  async function save() {
    try { await fetchAPI(editId ? `/api/profiles/${editId}` : '/api/profiles', { method: editId ? 'PATCH' : 'POST', body: JSON.stringify(form) }); resetForm(); await load(); setError(null) }
    catch (e) { setError(String(e)) }
  }
  async function sync(id: string) {
    setSyncingId(id)
    try { await fetchAPI(`/api/profiles/${id}/sync-sheet`, { method: 'POST' }); setRuleRefresh(current => ({ ...current, [id]: (current[id] ?? 0) + 1 })); setError(null) }
    catch (e) { setError(String(e)) }
    finally { setSyncingId(null) }
  }
  function edit(profile: Profile) { setEditId(profile.id); setForm({ name: profile.name, sheet_id_topics: profile.sheet_id_topics || '', folder_id_rules: profile.folder_id_rules || '', folder_id_output: profile.folder_id_output || '', workflow_mode: profile.workflow_mode, timezone: profile.timezone, default_time: profile.default_time, voice_provider: profile.voice_provider || 'openai', voice_id: profile.voice_id || 'marin', color: profile.color }) }
  return <div className="flex flex-col gap-4">
    <div><h1 className="m-0 text-lg font-semibold">Production Profiles</h1><p className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>Cấu hình thương hiệu, Video Rule và Spreadsheet kịch bản; mỗi tab là một video.</p></div>
    {error && <div className="text-xs" style={{ color: 'var(--red)' }}>{error}</div>}
    <Card className="py-4"><CardHeader><CardTitle className="text-xs">{editId ? 'CHỈNH SỬA PROFILE' : 'TẠO PROFILE'}</CardTitle></CardHeader><CardContent><div className="grid grid-cols-2 gap-3">{([['name','Tên Profile'],['sheet_id_topics','Spreadsheet ID hoặc URL'],['folder_id_rules','Folder VIDEO_RULES ID hoặc URL'],['folder_id_output','Folder OUTPUT ID hoặc URL'],['timezone','Timezone'],['default_time','Giờ mặc định'],['voice_id','Voice ID / Vbee voiceCode'],['color','Màu lịch']] as const).map(([key,label]) => <label key={key} className="text-[9px] flex flex-col gap-1" style={{ color: 'var(--muted)' }}>{label}<input type={key === 'color' ? 'color' : 'text'} value={form[key]} onChange={e => setForm({...form,[key]:e.target.value})} className={inputClass} style={inputStyle}/></label>)}<label className="text-[9px] flex flex-col gap-1" style={{ color: 'var(--muted)' }}>VOICE PROVIDER<select value={form.voice_provider} onChange={e=>setForm({...form,voice_provider:e.target.value,voice_id:e.target.value === 'vbee' ? '' : 'marin'})} className={inputClass} style={inputStyle}><option value="openai">OpenAI</option><option value="vbee">Vbee</option></select></label><label className="text-[9px] flex flex-col gap-1" style={{ color: 'var(--muted)' }}>WORKFLOW<select value={form.workflow_mode} onChange={e=>setForm({...form,workflow_mode:e.target.value})} className={inputClass} style={inputStyle}><option value="manual">manual</option><option value="semi_auto">semi_auto</option><option value="auto">auto</option></select></label></div><div className="mt-3 flex gap-2"><Button size="sm" disabled={!form.name.trim() || !form.voice_id.trim()} onClick={save}>{editId ? 'Lưu thay đổi' : 'Tạo Profile'}</Button>{editId && <Button size="sm" variant="outline" onClick={resetForm}>Hủy</Button>}</div></CardContent></Card>
    {profiles.map(p => <Card key={p.id} className="py-0 overflow-hidden"><CardContent className="flex items-center gap-3 py-4"><span className="w-2 h-2 rounded-full" style={{background:p.color}}/><div className="flex flex-col"><span className="text-xs">{p.name}</span><span className="text-[9px]" style={{color:'var(--muted)'}}>{p.workflow_mode} · {p.timezone} · OUTPUT: {p.folder_id_output ? 'đã cấu hình' : 'chưa cấu hình'}</span></div><Button className="ml-auto" size="xs" variant="outline" onClick={()=>edit(p)}>Chỉnh sửa</Button><Button size="xs" variant="outline" onClick={() => setOpenRuleProfileId(current => current === p.id ? null : p.id)}>{openRuleProfileId === p.id ? <ChevronUp/> : <ChevronDown/>} Xem Rule</Button><Button size="xs" disabled={syncingId === p.id} onClick={()=>sync(p.id)}>{syncingId === p.id ? 'Đang đồng bộ...' : 'Đồng bộ Rule + Sheet'}</Button></CardContent>{openRuleProfileId === p.id && <RuleViewer profileId={p.id} refreshKey={ruleRefresh[p.id] ?? 0}/>}</Card>)}
  </div>
}
