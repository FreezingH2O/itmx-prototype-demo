import { useEffect, useState } from 'react'
import { api, type Json } from './api'
import { time } from './format'
import { Icon, Logo } from './icons'
import { useRun } from './useRun'
import Institutions from './pages/Institutions'
import EnginePage from './pages/Engine'
import Merchant from './pages/Merchant'
import Results from './pages/Results'
import Landing from './pages/Landing'
import { t, useLang } from './i18n'
import { LangToggle } from './LangToggle'

type PageId = 'home' | 'institutions' | 'engine' | 'merchant' | 'results' | 'overview'
const PAGES: { id: PageId; label: string; key: string; icon: string }[] = [
  { id: 'institutions', label: 'Institutions', key: '1', icon: 'bank' },
  { id: 'engine', label: 'Our Engine', key: '2', icon: 'graph' },
  { id: 'merchant', label: 'Merchant', key: '3', icon: 'store' },
  { id: 'results', label: 'Experiment Results', key: '4', icon: 'chart' },
]
const LABELS: Record<string, string> = { overview: 'Overview', ...Object.fromEntries(PAGES.map((p) => [p.id, p.label])) }

function readPage(): PageId {
  const h = window.location.hash.replace('#', '') as PageId
  return ['home', 'institutions', 'engine', 'merchant', 'results', 'overview'].includes(h) ? h : 'home'
}

// Sidebar: hidden on Home. On wide screens it is expanded or collapsed to an icon rail, toggled from the
// button in its own header. On narrow screens it is an overlay drawer opened from the top bar menu button.
const narrow = () => window.matchMedia('(max-width: 860px)').matches

export default function App() {
  const { run, version, error, start, clock, setError } = useRun()
  useLang() // re-render the whole tree when the language changes
  const [page, setPage] = useState<PageId>(readPage)
  const [scenarios, setScenarios] = useState<Json[]>([])
  const [scenario, setScenario] = useState('merchant_300')
  const [mode, setMode] = useState<'live' | 'recorded'>('live')
  const [sideOpen, setSideOpen] = useState(() => !narrow())
  const home = page === 'home'
  const toggleSide = () => setSideOpen((o) => !o)
  const goto = (p: PageId) => { setPage(p); if (narrow()) setSideOpen(false) }
  // Picking a scenario or mode starts that run at once; the controls always show the run being viewed.
  const [starting, setStarting] = useState(false)
  const launch = async (s: string, m: 'live' | 'recorded') => {
    const info = scenarios.find((x) => x.id === s)
    const mm = m === 'recorded' && !info?.recording_available ? 'live' : m
    setScenario(s); setMode(mm); setStarting(true)
    try { await start(s, mm, info?.default_speed ?? 30) } finally { setStarting(false) }
  }
  // Entering the demo from Home always starts with the sidebar expanded on wide screens.
  const [wasHome, setWasHome] = useState(home)
  if (wasHome !== home) { setWasHome(home); if (!home) setSideOpen(!narrow()) }

  useEffect(() => { api.get('/v1/scenarios').then(setScenarios).catch(() => {}) }, [])
  useEffect(() => { window.location.hash = page }, [page])
  useEffect(() => {
    const onHash = () => setPage(readPage())
    const mq = window.matchMedia('(max-width: 860px)')
    const onWidth = () => setSideOpen(!narrow()) // drawer closes on narrow screens, expands on wide ones
    window.addEventListener('hashchange', onHash)
    mq.addEventListener('change', onWidth)
    return () => { window.removeEventListener('hashchange', onHash); mq.removeEventListener('change', onWidth) }
  }, [])
  // Keep the controls on the run actually shown (also when another tab or a failed start changes it).
  useEffect(() => { if (run && !starting) { setScenario(run.scenario); setMode(run.mode) } }, [run?.run_id, starting]) // eslint-disable-line

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return
      if (document.querySelector('.overlay')) return // expanded institution view handles its own keys
      const k = e.key.toLowerCase()
      if (e.code === 'Space') { e.preventDefault(); clock(run?.clock.playing ? 'pause' : 'play') }
      else if (e.key === 'ArrowRight') clock('step')
      else if ((k === 'b' || e.key === '[') && page !== 'home') toggleSide()
      else if (e.key === 'Escape' && narrow()) setSideOpen(false)
      else { const p = PAGES.find((x) => x.key === e.key); if (p) setPage(p.id) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [clock, run, page]) // eslint-disable-line react-hooks/exhaustive-deps

  const recorded = run?.mode === 'recorded'
  const modelError = run?.model?.status?.kind === 'error'
  const playing = !!run?.clock.playing
  const props = { run, version, present: false }
  const rail = !sideOpen // on wide screens a closed sidebar is an icon rail
  const tip = (label: string) => (rail ? t(label) : undefined)

  return (
    <div className={`shell ${home ? 'side-off' : ''} ${sideOpen ? '' : 'side-collapsed'}`}>
      <div className="side-scrim" onClick={toggleSide} aria-hidden="true" />
      <aside className="sidebar" aria-hidden={home} inert={home}>
        <div className="side-head">
          <button className="brand" onClick={() => goto('home')} title={t('Back to home')}>
            <span className="brand-mark"><Logo size={30} /></span>
            <span className="brand-text"><b>ทันเงิน</b><small>THAN NGERN</small></span>
          </button>
          <button className="side-collapse" onClick={toggleSide} aria-expanded={sideOpen}
            aria-label={t(sideOpen ? 'Collapse sidebar' : 'Expand sidebar')} title={`${t(sideOpen ? 'Collapse sidebar' : 'Expand sidebar')} (B)`}>
            <Icon name="sidebar" size={18} />
          </button>
        </div>
        <div className="side-label">{t('Views')}</div>
        <nav className="side-nav">
          {PAGES.map((p) => (
            <button key={p.id} className={page === p.id ? 'active' : ''} onClick={() => goto(p.id)} title={tip(p.label)} aria-label={t(p.label)}>
              <Icon name={p.icon} size={19} /><span className="lbl">{t(p.label)}</span><kbd className="lbl">{p.key}</kbd>
            </button>
          ))}
          <button className={page === 'overview' ? 'active' : ''} onClick={() => goto('overview')} title={tip('Overview')} aria-label={t('Overview')}>
            <Icon name="layout" size={19} /><span className="lbl">{t('Overview')}</span>
          </button>
        </nav>
        <div className="side-spacer" />
        <div className="side-group">
          <div className="side-label">{t('Simulation')}</div>
          <select value={scenario} onChange={(e) => launch(e.target.value, mode)} aria-label={t('Scenario')} disabled={starting}>
            {scenarios.map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
          </select>
          <select value={mode} onChange={(e) => launch(scenario, e.target.value as 'live' | 'recorded')} aria-label={t('Mode')} disabled={starting}>
            <option value="live">{t('Live inference')}</option>
            <option value="recorded" disabled={!scenarios.find((s) => s.id === scenario)?.recording_available}>{t('Recorded replay')}</option>
          </select>
          <button className="side-btn" title={rail ? t('Restart {s}', { s: scenario }) : undefined} aria-label={t('Restart run')} disabled={starting}
            onClick={() => launch(scenario, mode)}>
            <Icon name="refresh" size={18} /><span className="lbl">{t(starting ? 'Starting…' : 'Restart run')}</span>
          </button>
        </div>
        <div className="side-foot"><i /><span className="lbl">{t('Synthetic data only')}</span></div>
      </aside>

      <div className="main">
        {home ? (
          <Landing scenarios={scenarios} scenario={scenario} setScenario={setScenario} mode={mode} setMode={setMode}
            onOpen={goto}
            onStart={async (s, m, p) => { await launch(s, m); goto(p) }} />
        ) : <>
        <header className="topbar">
          <div className="tb-left">
            <button className="tb-icon tb-menu" onClick={toggleSide} aria-label={t('Open menu')} aria-expanded={sideOpen}>
              <Icon name="menu" size={18} />
            </button>
            <button className="tb-icon" onClick={() => goto('home')} aria-label={t('Home')} title={t('Home')}>
              <Icon name="home" size={18} />
            </button>
            <nav className="tb-crumbs" aria-label="Breadcrumb">
              <span>{t('Demo')}</span><Icon name="chevronRight" size={14} /><b>{t(LABELS[page])}</b>
            </nav>
            <span className="tb-case" title={t(run?.case_ids?.length ? 'Open case' : 'A case opens when the first report reaches the engine')}>
              <span className="scn">{starting ? t('Starting…') : run?.scenario ?? '…'}</span>
              {run?.case_ids?.length
                ? <>{run.case_ids[0]}{run.case_ids.length > 1 && <em>+{run.case_ids.length - 1}</em>}</>
                : <em>{t('Awaiting report')}</em>}
            </span>
          </div>
          <div className="tb-status">
            <span className="chip syn"><i />{t('Synthetic')}</span>
            {recorded
              ? <span className="chip rec"><i />{t('Recorded')} · {run?.recording}</span>
              : modelError && <span className="chip err"><i />{t('Model error')}</span>}
          </div>
          <div className="player" role="group" aria-label={t('Simulation controls')}>
            <div className="player-time" title={t('Simulated time, not real time')}>
              <span>{t('Sim time')}</span><b>{run ? time(run.clock.now) : '--:--:--'}</b>
            </div>
            <button className={`player-main ${playing ? 'on' : ''}`} onClick={() => clock(playing ? 'pause' : 'play')} disabled={!run}
              aria-label={t(playing ? 'Pause' : 'Play')} title={`${t(playing ? 'Pause' : 'Play')} (Space)`}>
              <Icon name={playing ? 'pause' : 'play'} size={15} />
            </button>
            <button className="player-btn" onClick={() => clock('step')} disabled={!run} aria-label={t('Step')} title={`${t('Step')} (→)`}><Icon name="step" size={15} /></button>
            <button className="player-btn" onClick={() => clock('reset')} disabled={!run} aria-label={t('Reset')} title={t('Reset')}><Icon name="reset" size={15} /></button>
            <select className="player-speed" value={run?.clock.speed ?? 30} onChange={(e) => clock('speed', { speed: Number(e.target.value) })} aria-label={t('Replay speed')} title={t('Replay speed')}>
              {[10, 30, 60, 120, ...(run?.large ? [600] : [])].map((s) => <option key={s} value={s}>{s}×</option>)}
            </select>
          </div>
          <LangToggle />
        </header>
        {error && <div className="error-bar"><span>{error}</span><button className="ghost" onClick={() => setError(null)}>{t('Dismiss')}</button></div>}
        {run?.notices?.length > 0 && <div className="notice-bar">{run.notices[run.notices.length - 1].text}</div>}

        {!run ? <div className="page empty">{t('Starting a run…')}</div> : page === 'overview' ? (
          <div className="overview">
            <div className="ov"><div className="ov-title">{t('Institutions')}</div><Institutions {...props} compact /></div>
            <div className="ov"><div className="ov-title">{t('Our Engine')}</div><EnginePage {...props} compact /></div>
            <div className="ov"><div className="ov-title">{t('Merchant')}</div><Merchant {...props} compact /></div>
          </div>
        ) : page === 'institutions' ? <Institutions {...props} />
          : page === 'engine' ? <EnginePage {...props} />
            : page === 'merchant' ? <Merchant {...props} />
              : <Results {...props} />}
        </>}
      </div>
    </div>
  )
}
