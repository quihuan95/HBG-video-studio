import { useCallback, useEffect, useState } from 'react'
import { fetchAPI } from '../api/client'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'

interface Profile { id: string; name: string; workflow_mode: string; timezone: string; default_time: string; sheet_id_topics?: string; folder_id_rules?: string; folder_id_output?: string; color: string; active: boolean }
const inputClass = 'text-xs px-2 py-1.5 rounded outline-none w-full'
const inputStyle = { background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)' }

export default function ContentProfilesPage() {
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [form, setForm] = useState({ name: '', sheet_id_topics: '', folder_id_rules: '', folder_id_output: '', workflow_mode: 'semi_auto', timezone: 'Asia/Ho_Chi_Minh', default_time: '09:00', color: '#22c55e' })
  const [editId, setEditId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(() => fetchAPI<Profile[]>('/api/profiles').then(setProfiles).catch(e => setError(String(e))), [])
  useEffect(() => { void load() }, [load])
  function resetForm() {
    setEditId(null)
    setForm({ name: '', sheet_id_topics: '', folder_id_rules: '', folder_id_output: '', workflow_mode: 'semi_auto', timezone: 'Asia/Ho_Chi_Minh', default_time: '09:00', color: '#22c55e' })
  }
  async function save() {
    try {
      await fetchAPI(editId ? `/api/profiles/${editId}` : '/api/profiles', { method: editId ? 'PATCH' : 'POST', body: JSON.stringify(form) })
      resetForm(); await load(); setError(null)
    }
    catch (e) { setError(String(e)) }
  }
  async function sync(id: string) {
    try { await fetchAPI(`/api/profiles/${id}/sync-sheet`, { method: 'POST' }); setError(null) }
    catch (e) { setError(String(e)) }
  }
  function edit(profile: Profile) {
    setEditId(profile.id)
    setForm({ name: profile.name, sheet_id_topics: profile.sheet_id_topics || '', folder_id_rules: profile.folder_id_rules || '', folder_id_output: profile.folder_id_output || '', workflow_mode: profile.workflow_mode, timezone: profile.timezone, default_time: profile.default_time, color: profile.color })
  }
  return <div className="flex flex-col gap-4">
    <div><h1 className="m-0 text-lg font-semibold">Production Profiles</h1><p className="text-[11px] mt-1" style={{ color: 'var(--muted)' }}>Cấu hình thương hiệu, Video Rule và Spreadsheet kịch bản; mỗi tab là một video.</p></div>
    {error && <div className="text-xs" style={{ color: 'var(--red)' }}>{error}</div>}
    <Card className="py-4"><CardHeader><CardTitle className="text-xs">{editId ? 'CHỈNH SỬA PROFILE' : 'TẠO PROFILE'}</CardTitle></CardHeader><CardContent>
      <div className="grid grid-cols-2 gap-3">
        {([['name','Tên Profile'],['sheet_id_topics','Spreadsheet ID hoặc URL'],['folder_id_rules','Folder VIDEO_RULES ID hoặc URL'],['folder_id_output','Folder OUTPUT ID hoặc URL'],['timezone','Timezone'],['default_time','Giờ mặc định'],['color','Màu lịch']] as const).map(([key,label]) =>
          <label key={key} className="text-[9px] flex flex-col gap-1" style={{ color: 'var(--muted)' }}>{label}<input type={key === 'color' ? 'color' : 'text'} value={form[key]} onChange={e => setForm({...form,[key]:e.target.value})} className={inputClass} style={inputStyle}/></label>)}
        <label className="text-[9px] flex flex-col gap-1" style={{ color: 'var(--muted)' }}>WORKFLOW<select value={form.workflow_mode} onChange={e=>setForm({...form,workflow_mode:e.target.value})} className={inputClass} style={inputStyle}><option value="manual">manual</option><option value="semi_auto">semi_auto</option><option value="auto">auto</option></select></label>
      </div><div className="mt-3 flex gap-2"><Button size="sm" disabled={!form.name.trim()} onClick={save}>{editId ? 'Lưu thay đổi' : 'Tạo Profile'}</Button>{editId && <Button size="sm" variant="outline" onClick={resetForm}>Hủy</Button>}</div>
    </CardContent></Card>
    {profiles.map(p => <Card key={p.id} className="py-4"><CardContent className="flex items-center gap-3"><span className="w-2 h-2 rounded-full" style={{background:p.color}}/><div className="flex flex-col"><span className="text-xs">{p.name}</span><span className="text-[9px]" style={{color:'var(--muted)'}}>{p.workflow_mode} · {p.timezone} · OUTPUT: {p.folder_id_output ? 'đã cấu hình' : 'chưa cấu hình'}</span></div><Button className="ml-auto" size="xs" variant="outline" onClick={()=>edit(p)}>Chỉnh sửa</Button><Button size="xs" onClick={()=>sync(p.id)}>Đồng bộ Rule + Sheet</Button></CardContent></Card>)}
  </div>
}
