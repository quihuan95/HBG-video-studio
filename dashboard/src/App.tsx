import { useState, useEffect } from 'react'
import { BrowserRouter, HashRouter, NavLink, Routes, Route, useLocation } from 'react-router-dom'
import { Files, ScrollText, BookOpen, SlidersHorizontal, Globe, CalendarDays, Layers, CirclePlus, Video, Search } from 'lucide-react'
import { TooltipProvider } from '@/components/ui/tooltip'
import { WebSocketProvider } from './api/WebSocketContext'
import { useWebSocketContext } from './api/useWebSocketContext'
import { LanguageProvider } from './i18n/LanguageContext'
import { useTranslation } from './i18n/useTranslation'
import { LANGS, LANG_LABELS, type Lang } from './i18n/translations'
import type { TranslationKey } from './i18n/translations'
import { fetchAPI } from './api/client'
import LogsPage from './pages/LogsPage'
import GuidePage from './pages/GuidePage'
import SettingsPage from './pages/SettingsPage'
import ContentCalendarPage from './pages/ContentCalendarPage'
import ContentProfilesPage from './pages/ContentProfilesPage'
import PostManagementPage from './pages/PostManagementPage'
import FootageSearchPage from './pages/FootageSearchPage'
import ReferenceAnalysisPage from './pages/ReferenceAnalysisPage'

const NAV: { to: string; icon: typeof Files; labelKey?: TranslationKey; label?: string; exact: boolean }[] = [
  { to: '/', icon: CirclePlus, label: 'Tạo video', exact: true },
  { to: '/produced-videos', icon: Video, label: 'Video đã tạo', exact: false },
  { to: '/content-profiles', icon: Layers, label: 'Production Profiles', exact: false },
  { to: '/calendar', icon: CalendarDays, label: 'Lịch sản xuất', exact: false },
  { to: '/footage-search', icon: Search, label: 'AI Footage Search', exact: false },
  { to: '/reference-analysis', icon: Video, label: 'Phân tích video tham khảo', exact: false },
  { to: '/logs', icon: ScrollText, labelKey: 'nav.logs', exact: false },
  { to: '/guide', icon: BookOpen, labelKey: 'nav.guide', exact: false },
  { to: '/settings', icon: SlidersHorizontal, labelKey: 'nav.settings', exact: false },
]

function useClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

function useBreadcrumbs() {
  const { t } = useTranslation()
  const loc = useLocation()
  const crumbs: string[] = []
  if (loc.pathname === '/') crumbs.push('Quản lý video', 'Tạo video')
  else if (loc.pathname.startsWith('/produced-videos')) crumbs.push('Quản lý video', 'Video đã tạo')
  else if (loc.pathname.startsWith('/content-profiles')) crumbs.push('Production Profiles')
  else if (loc.pathname.startsWith('/calendar')) crumbs.push('Lịch sản xuất')
  else if (loc.pathname.startsWith('/footage-search')) crumbs.push('AI Footage Search')
  else if (loc.pathname.startsWith('/reference-analysis')) crumbs.push('Phân tích video tham khảo')
  else if (loc.pathname.startsWith('/logs')) crumbs.push(t('app.breadcrumb.logs'))
  else if (loc.pathname.startsWith('/guide')) crumbs.push(t('app.breadcrumb.guide'))
  else if (loc.pathname.startsWith('/settings')) crumbs.push(t('app.breadcrumb.settings'))

  return crumbs
}

function LanguageSwitcher() {
  const { lang, setLang, t } = useTranslation()
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 text-[10px]" style={{ color: 'var(--muted)' }}>
        <Globe size={11} />
        <span>{t('app.language')}</span>
      </div>
      <select
        value={lang}
        onChange={e => setLang(e.target.value as Lang)}
        className="text-[10px] px-2 py-1.5 rounded outline-none w-full cursor-pointer"
        style={{ background: 'var(--card)', color: 'var(--text)', border: '1px solid var(--border)' }}
        aria-label={t('app.language')}
      >
        {LANGS.map(l => (
          <option key={l} value={l}>{LANG_LABELS[l]}</option>
        ))}
      </select>
    </div>
  )
}

function Sidebar() {
  const { t } = useTranslation()
  const { worker } = useWebSocketContext()
  const [health, setHealth] = useState<{ status: string; flow_enabled: boolean; extension_connected: boolean } | null>(null)

  useEffect(() => {
    fetchAPI<{ status: string; flow_enabled: boolean; extension_connected: boolean }>('/health').then(setHealth).catch(() => setHealth(null))
  }, [])

  return (
    <aside className="w-52 flex-shrink-0 flex flex-col border-r" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
      <div className="px-4 py-4 flex items-center gap-2.5 border-b" style={{ borderColor: 'var(--border)' }}>
        <span className="w-[22px] h-[22px] rounded flex items-center justify-center text-xs font-bold" style={{ background: 'var(--accent)', color: 'var(--bg)' }}>F</span>
        <div className="flex flex-col">
          <span className="text-xs font-bold tracking-widest">{t('app.brandName')}</span>
          <span className="text-[9px] tracking-wide" style={{ color: 'var(--muted)' }}>{t('app.brandTag')}</span>
        </div>
      </div>

      <nav className="flex flex-col gap-0.5 px-2.5 py-3">
        <div className="px-2.5 pb-1.5 text-[9px] font-semibold uppercase tracking-wider" style={{ color: 'var(--muted)' }}>Quản lý video</div>
        {NAV.map(({ to, icon: Icon, labelKey, label, exact }) => (
          <NavLink
            key={to}
            to={to}
            end={exact}
            className={`flex items-center gap-2.5 px-2.5 py-2 rounded text-xs transition-colors hover:opacity-90 ${to === '/' || to === '/produced-videos' ? 'ml-2' : ''}`}
            style={({ isActive }) => ({
              background: isActive ? 'var(--card)' : 'transparent',
              color: isActive ? 'var(--text)' : 'var(--muted)',
              borderLeft: `2px solid ${isActive ? 'var(--accent)' : 'transparent'}`,
            })}
          >
            <Icon size={13} />
            {labelKey ? t(labelKey) : label}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto px-4 py-3.5 border-t flex flex-col gap-2.5" style={{ borderColor: 'var(--border)' }}>
        <LanguageSwitcher />
        <div className="flex items-center justify-between text-[10px] tracking-wide" style={{ color: 'var(--muted)' }}>
          <span>{t('app.workers')}</span>
          <span style={{ color: 'var(--text)' }}>{worker ? `${worker.active}/${worker.active + worker.slots}` : '—'}</span>
        </div>
        <div className="flex items-center gap-1.5 text-[10px]" style={{ color: 'var(--muted)' }}>
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ background: health?.status === 'ok' ? 'var(--green)' : 'var(--red)' }}
          />
          {health?.status === 'ok' ? 'AI footage mode' : health ? 'Backend unavailable' : t('app.extensionChecking')}
        </div>
      </div>
    </aside>
  )
}

function Header() {
  const { lang, setLang, t } = useTranslation()
  const { isConnected } = useWebSocketContext()
  const crumbs = useBreadcrumbs()
  const clock = useClock()

  return (
    <header className="flex items-center gap-4 px-5 h-13 flex-shrink-0 border-b" style={{ background: 'var(--surface)', borderColor: 'var(--border)' }}>
      <div className="flex items-center gap-2 text-[11px] tracking-wide" style={{ color: 'var(--muted)' }}>
        <span style={{ color: 'var(--accent)' }}>{t('app.breadcrumbRoot')}</span>
        {crumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-2">
            <span>/</span>
            <span style={{ color: i === crumbs.length - 1 ? 'var(--text)' : 'var(--muted)' }}>{c}</span>
          </span>
        ))}
      </div>
      <span className="ml-auto" />
      <div className="flex items-center gap-3 text-[10px]" style={{ color: 'var(--muted)' }}>
        <div className="flex items-center gap-1.5 px-2 py-1 rounded border" style={{ borderColor: 'var(--border)' }}>
          <Globe size={11} style={{ color: 'var(--muted)' }} />
          <select
            value={lang}
            onChange={e => setLang(e.target.value as Lang)}
            className="text-[10px] bg-transparent outline-none cursor-pointer"
            style={{ color: 'var(--text)' }}
            aria-label={t('app.language')}
          >
            {LANGS.map(l => (
              <option key={l} value={l} style={{ background: 'var(--surface)', color: 'var(--text)' }}>
                {LANG_LABELS[l]}
              </option>
            ))}
          </select>
        </div>
        <span className="tracking-wide">{clock.toLocaleTimeString()}</span>
        <span className="flex items-center gap-1.5 px-2.5 py-1 rounded border" style={{ borderColor: 'var(--border)', color: isConnected ? 'var(--green)' : 'var(--red)' }}>
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ background: isConnected ? 'var(--green)' : 'var(--red)', animation: isConnected ? 'pulse 2s ease-in-out infinite' : 'none' }}
          />
          {isConnected ? t('app.wsLive') : t('app.wsDisconnected')}
        </span>
      </div>
    </header>
  )
}

function Layout() {
  return (
    <div className="flex h-screen overflow-hidden" style={{ background: 'var(--bg)', color: 'var(--text)' }}>
      <Sidebar />
      <div className="flex flex-col flex-1 overflow-hidden">
        <Header />
        <main className="flex-1 overflow-auto p-5">
          <Routes>
            <Route path="/" element={<PostManagementPage />} />
            <Route path="/produced-videos" element={<PostManagementPage view="created" />} />
            <Route path="/content-profiles" element={<ContentProfilesPage />} />
            <Route path="/calendar" element={<ContentCalendarPage />} />
            <Route path="/footage-search" element={<FootageSearchPage />} />
            <Route path="/reference-analysis" element={<ReferenceAnalysisPage />} />
            <Route path="/logs" element={<LogsPage />} />
            <Route path="/guide" element={<GuidePage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}

export default function App() {
  const Router = window.location.protocol === 'file:' ? HashRouter : BrowserRouter

  return (
    <Router>
      <LanguageProvider>
        <WebSocketProvider>
          <TooltipProvider>
            <Layout />
          </TooltipProvider>
        </WebSocketProvider>
      </LanguageProvider>
    </Router>
  )
}
