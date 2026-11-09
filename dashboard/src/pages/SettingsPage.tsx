import { useState, useEffect, useCallback } from 'react'
import { Globe } from 'lucide-react'
import { LANGS, LANG_LABELS, type Lang } from '../i18n/translations'
import { fetchAPI, patchAPI } from '../api/client'
import { useTranslation } from '../i18n/useTranslation'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardAction } from '../components/ui/card'
import { Button } from '../components/ui/button'

const CONTROL_CLASS = 'text-xs px-2 py-1.5 rounded outline-none w-full'
const CONTROL_STYLE = { background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)' }

interface SaveState {
  ok: boolean
  text: string
}

interface GoogleConnection {
  provider: 'google'
  status: 'active' | 'needs_reconnect' | 'not_connected'
  accountEmail: string | null
  accountName: string | null
}

interface OpenAISettings {
  has_api_key: boolean
  vision_model: string
  review_model: string
  script_model: string
  tts_model: string
  restart_required: boolean
}

// fetchAPI throws `API <status>: <body>` — pull the backend's `detail` back out so a 400 reads verbatim.
function apiDetail(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err)
  const body = raw.replace(/^API \d+: /, '')
  try {
    const parsed = JSON.parse(body) as { detail?: unknown }
    if (typeof parsed.detail === 'string') return parsed.detail
  } catch {
    // not JSON — fall through to the raw message
  }
  return raw
}

export default function SettingsPage() {
  const { lang, setLang, t } = useTranslation()
  const [google, setGoogle] = useState<GoogleConnection | null>(null)
  const [googleBusy, setGoogleBusy] = useState(false)
  const [googleError, setGoogleError] = useState<string | null>(null)
  const [openAI, setOpenAI] = useState<OpenAISettings | null>(null)
  const [openAIKey, setOpenAIKey] = useState('')
  const [openAIBusy, setOpenAIBusy] = useState(false)
  const [openAIMessage, setOpenAIMessage] = useState<SaveState | null>(null)

  const loadOpenAI = useCallback(async () => {
    try {
      setOpenAI(await fetchAPI<OpenAISettings>('/api/settings/openai'))
    } catch (err) {
      setOpenAIMessage({ ok: false, text: apiDetail(err) })
    }
  }, [])

  useEffect(() => { Promise.resolve().then(loadOpenAI) }, [loadOpenAI])

  function updateOpenAI(field: keyof OpenAISettings, value: string) {
    setOpenAI(prev => prev ? { ...prev, [field]: value } : prev)
    setOpenAIMessage(null)
  }

  async function saveOpenAI() {
    if (!openAI) return
    setOpenAIBusy(true)
    setOpenAIMessage(null)
    try {
      const result = await patchAPI<OpenAISettings>('/api/settings/openai', {
        api_key: openAIKey,
        vision_model: openAI.vision_model,
        review_model: openAI.review_model,
        script_model: openAI.script_model,
        tts_model: openAI.tts_model,
      })
      setOpenAI(result)
      setOpenAIKey('')
      setOpenAIMessage({ ok: true, text: 'Đã lưu. Hãy khởi động lại ứng dụng để mọi service nhận cấu hình mới.' })
    } catch (err) {
      setOpenAIMessage({ ok: false, text: apiDetail(err) })
    } finally {
      setOpenAIBusy(false)
    }
  }

  const loadGoogle = useCallback(async () => {
    try {
      setGoogle(await fetchAPI<GoogleConnection>('/api/oauth/google/status'))
    } catch (err) {
      setGoogleError(apiDetail(err))
    }
  }, [])

  useEffect(() => { Promise.resolve().then(loadGoogle) }, [loadGoogle])

  async function connectGoogle() {
    setGoogleBusy(true)
    setGoogleError(null)
    try {
      const result = await fetchAPI<{ authorizationUrl: string }>('/api/oauth/google/start')
      window.open(result.authorizationUrl, '_blank', 'noopener,noreferrer')
    } catch (err) {
      setGoogleError(apiDetail(err))
    } finally {
      setGoogleBusy(false)
    }
  }

  async function disconnectGoogle() {
    setGoogleBusy(true)
    setGoogleError(null)
    try {
      await fetchAPI('/api/oauth/google/connection', { method: 'DELETE' })
      await loadGoogle()
    } catch (err) {
      setGoogleError(apiDetail(err))
    } finally {
      setGoogleBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <h1 className="m-0 text-lg font-semibold" style={{ color: 'var(--text)' }}>{t('settings.title')}</h1>
        <span className="text-[11px]" style={{ color: 'var(--muted)' }}>{t('settings.desc')}</span>
      </div>

      <Card className="py-4">
        <CardHeader>
          <CardTitle className="text-xs tracking-widest uppercase flex items-center gap-1.5">
            <Globe size={13} style={{ color: 'var(--accent)' }} />
            {t('settings.language.title')}
          </CardTitle>
          <CardDescription className="text-[11px]">{t('settings.language.desc')}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="max-w-xs">
            <select
              value={lang}
              onChange={e => setLang(e.target.value as Lang)}
              className={CONTROL_CLASS}
              style={CONTROL_STYLE}
            >
              {LANGS.map(l => (
                <option key={l} value={l}>{LANG_LABELS[l]}</option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>

      <Card className="py-4">
        <CardHeader>
          <CardTitle className="text-xs tracking-widest uppercase">OpenAI</CardTitle>
          <CardDescription className="text-[11px]">
            API key được lưu trong file .env local và không bao giờ được trả lại giao diện.
          </CardDescription>
          <CardAction>
            <Button size="sm" disabled={openAIBusy || !openAI} onClick={saveOpenAI}>
              {openAIBusy ? 'Đang lưu' : 'Lưu OpenAI'}
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          {openAI ? (
            <div className="flex flex-col gap-3">
              <div className="grid gap-3" style={{ gridTemplateColumns: '1fr 1fr' }}>
                <label className="flex flex-col gap-1 text-[9px] tracking-widest" style={{ color: 'var(--muted)' }}>
                  API KEY {openAI.has_api_key ? '· ĐÃ CẤU HÌNH' : '· CHƯA CÓ'}
                  <input
                    type="password"
                    autoComplete="new-password"
                    value={openAIKey}
                    onChange={e => setOpenAIKey(e.target.value)}
                    placeholder={openAI.has_api_key ? 'Để trống để giữ key hiện tại' : 'sk-...'}
                    className={CONTROL_CLASS}
                    style={CONTROL_STYLE}
                  />
                </label>
                {([
                  ['vision_model', 'VISION / PHÂN LOẠI FOOTAGE'],
                  ['review_model', 'VIDEO REVIEW'],
                  ['script_model', 'SCRIPT / TIMELINE'],
                  ['tts_model', 'TEXT TO SPEECH'],
                ] as const).map(([field, label]) => (
                  <label key={field} className="flex flex-col gap-1 text-[9px] tracking-widest" style={{ color: 'var(--muted)' }}>
                    {label}
                    <input
                      value={openAI[field]}
                      onChange={e => updateOpenAI(field, e.target.value)}
                      className={CONTROL_CLASS}
                      style={CONTROL_STYLE}
                    />
                  </label>
                ))}
              </div>
              {openAIMessage && (
                <span className="text-[10px]" style={{ color: openAIMessage.ok ? 'var(--green)' : 'var(--red)' }}>
                  {openAIMessage.text}
                </span>
              )}
            </div>
          ) : (
            <span className="text-[10px]" style={{ color: 'var(--muted)' }}>Đang tải cấu hình OpenAI…</span>
          )}
        </CardContent>
      </Card>

      <Card className="py-4">
        <CardHeader>
          <CardTitle className="text-xs tracking-widest uppercase">Google Drive &amp; Sheets</CardTitle>
          <CardDescription className="text-[11px]">
            {google?.status === 'active'
              ? `${google.accountName ?? 'Google'} · ${google.accountEmail ?? ''}`
              : google?.status === 'needs_reconnect'
                ? 'Phiên Google đã hết hạn, hãy kết nối lại.'
                : 'Kết nối Google để đọc Sheet, đọc footage và ghi video lên Drive.'}
          </CardDescription>
          <CardAction>
            {google?.status === 'active' ? (
              <Button variant="outline" size="sm" disabled={googleBusy} onClick={disconnectGoogle}>Ngắt kết nối</Button>
            ) : (
              <Button size="sm" disabled={googleBusy} onClick={connectGoogle}>Kết nối Google</Button>
            )}
          </CardAction>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3 text-[10px]">
            <span style={{ color: google?.status === 'active' ? 'var(--green)' : 'var(--muted)' }}>
              {google?.status ?? 'loading'}
            </span>
            <Button variant="outline" size="xs" disabled={googleBusy} onClick={loadGoogle}>Kiểm tra lại</Button>
            {googleError && <span style={{ color: 'var(--red)' }}>{googleError}</span>}
          </div>
        </CardContent>
      </Card>

      {/* Legacy provider selector removed: OpenAI is configured in the card above.
      <Card className="py-4">
        <CardHeader>
          <CardTitle className="text-xs tracking-widest uppercase">{t('settings.providers.title')}</CardTitle>
          <CardDescription className="text-[11px]">OpenAI API là nhà cung cấp AI duy nhất của ứng dụng.</CardDescription>
          <CardAction>
            <Button variant="outline" size="sm" disabled={testing} onClick={runTest}>
              {testing ? t('settings.testing') : t('settings.test')}
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          {testError && <div className="text-[10px] pb-2" style={{ color: 'var(--red)' }}>{testError}</div>}
          <div className="flex flex-col gap-1.5">
            {Object.entries(providers).map(([name, info]) => (
              <div key={name} className="flex items-center gap-3 text-[11px]">
                <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: info.installed ? 'var(--green)' : 'var(--red)' }} />
                <span style={{ width: 90 }}>{info.binary ?? name}</span>
                <span style={{ color: 'var(--muted)', width: 100 }}>
                  {info.installed ? t('settings.providers.installed') : t('settings.providers.missing')}
                </span>
                <span style={{ width: 100, color: info.tested === null ? 'var(--muted)' : info.tested ? 'var(--green)' : 'var(--red)' }}>
                  {info.tested === null ? t('settings.providers.untested') : info.tested ? t('settings.providers.ok') : t('settings.providers.failed')}
                </span>
                {info.error && <span className="truncate" style={{ color: 'var(--muted)' }}>{info.error}</span>}
                {name === data.active && (
                  <span className="ml-auto text-[9px] tracking-widest flex-shrink-0" style={{ color: 'var(--accent)' }}>{t('settings.activeProvider')}</span>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {roleIds.length === 0 ? (
        <div className="text-xs" style={{ color: 'var(--muted)' }}>{t('settings.empty')}</div>
      ) : roleIds.map(roleId => {
        const draft = drafts[roleId]
        const meta = data.role_meta[roleId]
        const info = providers[draft.provider]
        const efforts = info?.efforts ?? []
        const catalog = models[draft.provider]
        const modelList = catalog?.models ?? []
        const authoritative = catalog?.authoritative ?? false
        const modelBusy = modelsLoading[draft.provider] ?? false
        const custom = customModel[roleId] ?? false
        const knownModel = draft.model !== null && modelList.some(m => m.id === draft.model)
        const effortLocked = (info?.model_encodes_effort ?? false) && draft.model !== null
        const dirty = !sameAssignment(draft, data.roles[roleId])
        const busy = saving[roleId] ?? false
        const state = saveState[roleId]

        return (
          <Card key={roleId} className="py-4">
            <CardHeader>
              <CardTitle className="text-xs tracking-widest uppercase">{meta?.label ?? roleId}</CardTitle>
              <CardDescription className="text-[11px]">{meta?.description ?? roleId}</CardDescription>
              <CardAction>
                <span className="text-[9px] tracking-widest" style={{ color: dirty ? 'var(--yellow)' : 'var(--muted)' }}>
                  {dirty ? t('settings.unsaved') : t('settings.inSync')}
                </span>
              </CardAction>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3.5 items-start" style={{ gridTemplateColumns: '1fr 1.6fr 1fr' }}>
                <div className="flex flex-col gap-1">
                  <span className="text-[9px] tracking-widest" style={{ color: 'var(--muted)' }}>{t('settings.field.agent')}</span>
                  <select
                    value={draft.provider}
                    onChange={e => changeProvider(roleId, e.target.value)}
                    className={CONTROL_CLASS}
                    style={CONTROL_STYLE}
                  >
                    {Object.entries(providers).map(([name, p]) => (
                      <option key={name} value={name} disabled={!p.installed}>
                        {p.installed ? (p.binary ?? name) : `${p.binary} · ${t('settings.notInstalled')}`}
                      </option>
                    ))}
                  </select>
                  {info && !info.installed && (
                    <span className="text-[10px] leading-snug" style={{ color: 'var(--red)' }}>
                      {t('settings.installHint', { binary: info.binary ?? draft.provider })}
                    </span>
                  )}
                </div>

                <div className="flex flex-col gap-1">
                  <span className="text-[9px] tracking-widest" style={{ color: 'var(--muted)' }}>{t('settings.field.model')}</span>
                  <div className="flex items-center gap-1.5">
                    {custom ? (
                      <input
                        value={draft.model ?? ''}
                        onChange={e => setModel(roleId, e.target.value === '' ? null : e.target.value)}
                        placeholder={t('settings.modelCustomPlaceholder')}
                        className={CONTROL_CLASS}
                        style={CONTROL_STYLE}
                      />
                    ) : (
                      <select
                        value={draft.model ?? DEFAULT_OPTION}
                        onChange={e => selectModel(roleId, e.target.value)}
                        className={CONTROL_CLASS}
                        style={CONTROL_STYLE}
                      >
                        <option value={DEFAULT_OPTION}>{t('settings.optionDefault')}</option>
                        {modelList.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
                        {draft.model !== null && !knownModel && <option value={draft.model}>{draft.model}</option>}
                        {!authoritative && <option value={CUSTOM_OPTION}>{t('settings.optionCustom')}</option>}
                      </select>
                    )}
                    <Button
                      variant="outline"
                      size="icon-xs"
                      aria-label={t('settings.refreshModels')}
                      title={t('settings.refreshModels')}
                      disabled={modelBusy}
                      onClick={() => { loadModels(draft.provider, true) }}
                    >
                      <RefreshCw className={modelBusy ? 'animate-spin' : undefined} />
                    </Button>
                  </div>
                  <span className="text-[10px] leading-snug" style={{ color: 'var(--muted)' }}>
                    {modelBusy
                      ? t('settings.modelsLoading')
                      : modelList.length === 0
                        ? t('settings.modelsEmpty')
                        : !authoritative
                          ? t('settings.modelsFreeText')
                          : ''}
                  </span>
                  {custom && (
                    <button
                      type="button"
                      className="text-[10px] text-left cursor-pointer bg-transparent border-0 p-0"
                      style={{ color: 'var(--accent)' }}
                      onClick={() => {
                        setCustomModel(prev => ({ ...prev, [roleId]: false }))
                        setModel(roleId, null)
                      }}
                    >
                      {t('settings.modelBackToList')}
                    </button>
                  )}
                </div>

                <div className="flex flex-col gap-1">
                  <span className="text-[9px] tracking-widest" style={{ color: 'var(--muted)' }}>{t('settings.field.effort')}</span>
                  <select
                    value={effortLocked ? DEFAULT_OPTION : draft.effort ?? DEFAULT_OPTION}
                    disabled={effortLocked}
                    onChange={e => updateDraft(roleId, { effort: e.target.value === DEFAULT_OPTION ? null : e.target.value })}
                    className={CONTROL_CLASS}
                    style={{ ...CONTROL_STYLE, opacity: effortLocked ? 0.5 : 1 }}
                  >
                    <option value={DEFAULT_OPTION}>{t('settings.optionDefault')}</option>
                    {efforts.map(x => <option key={x} value={x}>{x}</option>)}
                  </select>
                  {effortLocked && (
                    <span className="text-[10px] leading-snug" style={{ color: 'var(--muted)' }}>
                      {t('settings.effortLockedHint', { binary: info.binary ?? draft.provider })}
                    </span>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-3 pt-3.5">
                <Button size="sm" disabled={!dirty || busy} onClick={() => save(roleId)}>
                  {busy ? t('settings.saving') : t('settings.save')}
                </Button>
                {state && (
                  <span className="text-[10px] leading-snug" style={{ color: state.ok ? 'var(--green)' : 'var(--red)' }}>{state.text}</span>
                )}
              </div>
            </CardContent>
          </Card>
        )
      })} */}
    </div>
  )
}
