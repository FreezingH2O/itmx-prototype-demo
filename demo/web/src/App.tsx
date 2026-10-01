import { useEffect, useState } from 'react'
import { api, type Json } from './api'
import { time } from './format'
import { Icon, Logo } from './icons'
import { useRun } from './useRun'
import Institutions from './pages/Institutions'
import EnginePage from './pages/Engine'
import Merchant from './pages/Merchant'
import Results from './pages/Results'

type PageId = 'institutions' | 'engine' | 'merchant' | 'results' | 'overview'
const PAGES: { id: PageId; label: string; key: string; icon: string }[] = [
  { id: 'institutions', label: 'Institutions', key: '1', icon: 'bank' },
  { id: 'engine', label: 'Our Engine', key: '2', icon: 'graph' },
  { id: 'merchant', label: 'Merchant', key: '3', icon: 'store' },
  { id: 'results', label: 'Experiment Results', key: '4', icon: 'chart' },
]
const DEMO_ORDER: PageId[] = ['merchant', 'institutions', 'engine', 'institutions', 'merchant', 'results']

function readPage(): PageId {
  const h = window.location.hash.replace('#', '') as PageId
  return ['institutions', 'engine', 'merchant', 'results', 'overview'].includes(h) ? h : 'institutions'
}

export default function App() {
  const { run, version, error, start, clock, setError } = useRun()
  const [page, setPage] = useState<PageId>(readPage)
  const [present, setPresent] = useState(false)
  const [demoIdx, setDemoIdx] = useState(0)
  const [scenarios, setScenarios] = useState<Json[]>([])
  const [scenario, setScenario] = useState('merchant_300')
  const [mode, setMode] = useState<'live' | 'recorded'>('live')

  useEffect(() => { api.get('/v1/scenarios').then(setScenarios).catch(() => {}) }, [])
  useEffect(() => { window.location.hash = page }, [page])
  useEffect(() => { document.body.classList.toggle('present', present) }, [present])
  useEffect(() => { if (run) { setScenario(run.scenario); setMode(run.mode) } }, [run?.run_id]) // eslint-disable-line

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return
      if (document.querySelector('.overlay')) return // expanded institution view handles its own keys
      const k = e.key.toLowerCase()
      if (e.code === 'Space') { e.preventDefault(); clock(run?.clock.playing ? 'pause' : 'play') }
      else if (e.key === 'ArrowRight') clock('step')
      else if (k === 'p') setPresent((p) => !p)
      else if (e.key === 'Escape') setPresent(false)
      else if (k === 'n' && present) { const i = (demoIdx + 1) % DEMO_ORDER.length; setDemoIdx(i); setPage(DEMO_ORDER[i]) }
      else { const p = PAGES.find((x) => x.key === e.key); if (p) setPage(p.id) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [clock, run, present, demoIdx])

  const recorded = run?.mode === 'recorded'
  const modelError = run?.model?.status?.kind === 'error'
  const playing = !!run?.clock.playing
  const props = { run, version, present }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <Logo size={92} />
          <div className="brand-name">ทางเชื่อม</div>
          <div className="brand-sub">Bank × Crypto Risk Graph</div>
        </div>
        <nav className="side-nav">
          {PAGES.map((p) => (
            <button key={p.id} className={page === p.id ? 'active' : ''} onClick={() => setPage(p.id)}>
              <span className="n">0{p.key}</span><Icon name={p.icon} size={20} />{p.label}
            </button>
          ))}
        </nav>
        <div className="side-spacer" />
        <div className="side-group">
          <span className="side-label">Scenario</span>
          <select value={scenario} onChange={(e) => setScenario(e.target.value)} aria-label="Scenario">
            {scenarios.map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
          </select>
          <select value={mode} onChange={(e) => setMode(e.target.value as 'live' | 'recorded')} aria-label="Mode">
            <option value="live">Live inference</option>
            <option value="recorded" disabled={!scenarios.find((s) => s.id === scenario)?.recording_available}>Recorded replay</option>
          </select>
          <button className="side-btn" onClick={() => start(scenario, mode)}><Icon name="refresh" />New run</button>
        </div>
        <div className="side-group">
          <button className={`side-btn ${page === 'overview' ? 'on' : ''}`} onClick={() => setPage('overview')}><Icon name="home" />Overview</button>
          <button className={`side-btn ${present ? 'on' : ''}`} onClick={() => setPresent((p) => !p)}
            title="Keys: Space play/pause, → step, 1-4 pages, n next demo page">
            <Icon name="present" />{present ? 'Exit presentation' : 'Presentation'}
          </button>
        </div>
        <div className="side-foot">SYNTHETIC DATA</div>
      </aside>

      <div className="main">
        <header className="topbar">
          <span className="case-id">{run?.case_ids?.[0] ?? 'NO CASE YET'}</span>
          <span className="vsep" />
          <span className="tpill syn">Synthetic simulation</span>
          {recorded
            ? <span className="tpill rec">RECORDED · {run?.recording}</span>
            : <span className={`tpill ${modelError ? 'err' : 'live'}`}>LIVE · {run?.model?.model_id ?? 'model'}</span>}
          <span className="vsep" />
          <span className="sim-time" title="Simulated time, not real time">Simulation time <b>{run ? time(run.clock.now) : '--:--:--'}</b></span>
          <span className="top-spacer" />
          <div className="controls">
            <button className={playing ? 'on' : ''} onClick={() => clock('play')} disabled={!run || playing}><Icon name="play" size={15} />Play</button>
            <button onClick={() => clock('pause')} disabled={!run || !playing}><Icon name="pause" size={15} />Pause</button>
            <button onClick={() => clock('step')} disabled={!run}><Icon name="step" size={15} />Step</button>
            <button onClick={() => clock('reset')} disabled={!run}><Icon name="reset" size={15} />Reset</button>
            <select value={run?.clock.speed ?? 30} onChange={(e) => clock('speed', { speed: Number(e.target.value) })} aria-label="Replay speed">
              {[10, 30, 60, 120].map((s) => <option key={s} value={s}>{s}×</option>)}
            </select>
          </div>
        </header>
        {error && <div className="error-bar"><span>{error}</span><button className="ghost" onClick={() => setError(null)}>Dismiss</button></div>}
        {run?.notices?.length > 0 && <div className="notice-bar">{run.notices[run.notices.length - 1].text}</div>}

        {!run ? <div className="page empty">Starting a run…</div> : page === 'overview' ? (
          <div className="overview">
            <div className="ov"><div className="ov-title">Institutions</div><Institutions {...props} compact /></div>
            <div className="ov"><div className="ov-title">Our Engine</div><EnginePage {...props} compact /></div>
            <div className="ov"><div className="ov-title">Merchant</div><Merchant {...props} compact /></div>
          </div>
        ) : page === 'institutions' ? <Institutions {...props} />
          : page === 'engine' ? <EnginePage {...props} />
            : page === 'merchant' ? <Merchant {...props} />
              : <Results {...props} />}
      </div>
    </div>
  )
}
