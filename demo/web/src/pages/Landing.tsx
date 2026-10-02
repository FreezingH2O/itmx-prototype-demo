import { useState } from 'react'
import type { Json } from '../api'
import { Icon, Logo } from '../icons'

// Landing page: what the prototype is, which case to try first, and how to drive the demo.
type Target = 'institutions' | 'engine' | 'merchant' | 'results'
type Props = {
  scenarios: Json[]
  scenario: string
  setScenario: (s: string) => void
  mode: 'live' | 'recorded'
  setMode: (m: 'live' | 'recorded') => void
  onStart: (scenario: string, mode: 'live' | 'recorded', page: Target) => void
  onOpen: (page: Target) => void
}

const SOURCES = [
  { icon: 'bank', name: 'Bank', text: 'Transfers and customer records' },
  { icon: 'swap', name: 'Exchange', text: 'THB deposits, trades and withdrawals' },
  { icon: 'cube', name: 'Blockchain', text: 'On-chain transfers and addresses' },
]

const CAPABILITIES = [
  { icon: 'graph', title: 'Trace connected records', text: 'Link bank, exchange and on-chain records into one case, and show which links are verified and which are inferred.' },
  { icon: 'file', title: 'Understand the context', text: 'Read risk reasons next to benign activity and missing information, so a reviewer sees the whole picture before acting.' },
  { icon: 'lock', title: 'Act in proportion', text: 'Send evidence-backed recommendations to the responsible institution: hold the suspicious amount, not the whole account.' },
]

type Case = {
  id: string; title: string; badge: string; focus: string; page: Target; pageLabel: string
  short: string; summary: string; story: [string, string][]; tryThis: string; stats: [string, string, string?][]
}
const CASES: Case[] = [
  {
    id: 'merchant_300', title: 'The ฿300 merchant payment', badge: 'Recommended first', focus: 'Proportionate hold',
    page: 'merchant', pageLabel: 'Merchant',
    short: 'A mule pays ฿300 at an innocent shop. Hold just that amount, not the whole account.',
    summary: 'A scam victim pays a mule account, which splits the money, buys USDT through an exchange and also pays ฿300 at a small chicken-rice shop. The question is how to stop the money without freezing an innocent shop.',
    story: [
      ['10:00', 'Victim at Bank A sends ฿50,000 to mule account A-1001.'],
      ['10:04', 'A-1001 forwards ฿16,000 to each of two Bank B mule accounts.'],
      ['10:06', 'A-1001 also pays ฿300 by QR at ร้านป้ามะลิ, an ordinary shop at Bank B.'],
      ['10:12', 'Both deposit to the exchange with bank references and buy about 454 USDT each.'],
      ['10:20', 'The victim report arrives. The engine links bank, exchange and chain into one case.'],
      ['10:22', 'A 454 USDT withdrawal to a TRON address linked to a flagged wallet. It can still be held until 10:40.'],
    ],
    tryThis: 'Restrict only ฿300 at the shop and hold the withdrawal. Then submit the sale receipt as the merchant and release it as the officer.',
    stats: [['฿300', 'held at the shop', 'amber'], ['฿10,000', 'stays usable', 'teal'], ['454 USDT', 'withdrawal to hold']],
  },
  {
    id: 'network_day', title: 'A full day of a mule network', badge: 'Scale mode', focus: 'Volume and innocent bystanders',
    page: 'institutions', pageLabel: 'Institutions',
    short: 'A whole day of a mule network across 5 banks: the volume, and the innocent people caught in it.',
    summary: 'One simulated day modelled on public Thai cases: a scam network moves victim money through bought and rented mule accounts at 5 banks, then out through an exchange, OTC USDT sellers and gold shops. Many of the accounts it touches belong to innocent people.',
    story: [
      ['00:00', 'The day begins. Over the day 153 victims pay into 80 mule accounts (60 bought, 20 rented) across 5 banks.'],
      ['~18 min', 'Typical time from a victim payment to the money leaving: OTC sellers 48%, exchange 33%, gold shops 18%.'],
      ['All day', 'Look-alikes trip simple rules: dorm owners on rent day, online shops, students tricked into a "refund", 40 merchants paid by mules.'],
      ['15:03', 'ร้านป้ามะลิ at Bank E is reported over a single ฿478 payment from a mule. Follow it in Merchant.'],
    ],
    tryThis: 'Runs at 600×. Watch the "awaiting an officer" queue grow in Institutions, then open Our Engine to follow one reported account through the network graph.',
    stats: [['฿36.9M', 'victim losses', 'amber'], ['93', 'report signals'], ['5 + 1', 'banks + exchange']],
  },
  {
    id: 'missing_reference', title: 'Missing deposit references', badge: 'Case 02', focus: 'Uncertainty',
    page: 'engine', pageLabel: 'Our Engine',
    short: 'Deposits arrive with no bank reference. See how the engine handles links it cannot prove.',
    summary: 'The same money flow, but the exchange deposits arrive without a bank reference. Both are ฿16,000, so amount and time alone cannot prove which bank account paid which exchange customer.',
    story: [
      ['10:04', 'Two Bank B mule accounts each receive ฿16,000, as in the merchant case.'],
      ['10:12', 'Two equal THB deposits reach the exchange with no reference to match them.'],
      ['10:20', 'The report arrives. Bank-to-exchange links stay candidate or unresolved, not verified.'],
    ],
    tryThis: 'Open Our Engine and compare verified links with candidate ones. Notice the engine lists the missing evidence and does not recommend an exchange restriction it cannot support.',
    stats: [['0', 'verified exchange links'], ['2', 'equal ฿16,000 deposits'], ['No', 'restriction recommended']],
  },
  {
    id: 'late_broadcast', title: 'Withdrawal already broadcast', badge: 'Case 03', focus: 'Timing',
    page: 'institutions', pageLabel: 'Institutions',
    short: 'The report arrives after the crypto has left. See why the control deadline matters.',
    summary: 'The money moves faster than the report. The USDT withdrawal is requested and sent on-chain before the victim report reaches the engine, so the hold window has already closed.',
    story: [
      ['10:16', 'Withdrawal requested. It can only be held for 2 minutes, until 10:18.'],
      ['10:18', 'The window closes and the withdrawal is broadcast to the TRON network.'],
      ['10:20', 'The report arrives, two minutes too late to hold the crypto.'],
    ],
    tryThis: 'Check the exchange panel in Institutions: the withdrawal is already on-chain and cannot be held, but the bank-side trail is still traced. This is why report speed and shared data matter.',
    stats: [['2 min', 'hold window'], ['2 min', 'report arrives late'], ['0 USDT', 'left to hold']],
  },
]

const STEPS = [
  { title: 'Start a run', text: 'Pick a scenario and press Start. Use Play or Step in the top bar to advance simulated time.' },
  { title: 'Inspect the evidence', text: 'Open Our Engine to review links, risk reasons, benign context and missing data.' },
  { title: 'Try the merchant review', text: 'In Institutions, hold only ฿300. Submit the sample receipt in Merchant, then return for officer review.' },
  { title: 'Check the outcome', text: 'Revisit Merchant after the decision. Experiment Results stays not_run until a completed bundle is loaded.' },
]

const KEYS: [string, string][] = [['Space', 'Play / pause'], ['→', 'Step'], ['1–4', 'Switch page'], ['B', 'Collapse sidebar (demo pages)']]

export default function Landing({ scenarios, scenario, setScenario, mode, setMode, onStart, onOpen }: Props) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const toggle = (id: string) => setOpen((o) => ({ ...o, [id]: !o[id] }))
  const recAvailable = !!scenarios.find((s) => s.id === scenario)?.recording_available
  const go = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  const pageFor = (id: string): Target => CASES.find((c) => c.id === id)?.page ?? 'institutions'

  return (
    <div className="lp">
      <header className="lp-header">
        <div className="lp-brand">
          <span className="lp-mark"><Logo size={30} /></span>
          <span><b>ทางเชื่อม</b><small>Bank × Crypto Risk Graph</small></span>
        </div>
        <nav className="lp-links">
          <button onClick={() => go('lp-engine')}>Our engine</button>
          <button onClick={() => go('lp-cases')}>Demo cases</button>
          <button onClick={() => go('lp-how')}>How to use</button>
        </nav>
        <span className="lp-spacer" />
        <span className="lp-chip"><i />Synthetic prototype</span>
        <button className="lp-btn primary sm" onClick={() => onOpen('institutions')}>Open demo<Icon name="arrowRight" size={16} /></button>
      </header>

      <section className="lp-hero">
        <div className="lp-hero-copy">
          <div className="lp-eyebrow">Bank × Crypto Risk Graph</div>
          <h1>Connect the evidence.<br /><span>Support the decision.</span></h1>
          <p className="lp-lede">
            <b>ทางเชื่อม</b> brings bank transactions, exchange activity and blockchain evidence into one reviewable view.
            Officers see the full context and decide the next action.
          </p>
          <div className="lp-cta">
            <button className="lp-btn primary" onClick={() => go('lp-cases')}>Explore the demo<Icon name="arrowRight" size={18} /></button>
            <button className="lp-btn ghost-dark" onClick={() => go('lp-how')}>How it works<Icon name="arrowDown" size={18} /></button>
          </div>
          <div className="lp-hero-foot">
            <span><Icon name="database" size={15} />Synthetic data</span>
            <span><Icon name="user" size={15} />Human review at every decision</span>
          </div>
        </div>

        <figure className="lp-flow" aria-label="How evidence flows to an officer decision">
          <figcaption>From evidence to review</figcaption>
          <div className="lp-sources">
            {SOURCES.map((s) => (
              <div key={s.name} className="lp-src">
                <span className="ic"><Icon name={s.icon} size={20} /></span>
                <b>{s.name}</b><small>{s.text}</small>
              </div>
            ))}
          </div>
          <svg className="lp-merge" viewBox="0 0 300 36" preserveAspectRatio="none" aria-hidden="true">
            <path d="M50 0 C50 26 150 10 150 36" /><path d="M150 0 V36" /><path d="M250 0 C250 26 150 10 150 36" />
          </svg>
          <div className="lp-engine-node">
            <b>Our Engine</b><small>Link · Trace · Explain</small>
          </div>
          <span className="lp-vline" />
          <div className="lp-node"><b>Evidence + recommendations</b><small>Verified links · Risk reasons · Missing context</small></div>
          <span className="lp-vline" />
          <div className="lp-node officer"><span className="ic"><Icon name="user" size={16} /></span><div><b>Officer decision</b><small>Reviewed by the responsible institution</small></div></div>
          <p className="lp-flow-note">Recommendations support review. They never move funds.</p>
        </figure>
      </section>

      <div className="lp-body">
        <div className="lp-about">
          <b>About this prototype</b>
          <span><Icon name="database" size={15} />Synthetic scenarios</span>
          <span><Icon name="lock" size={15} />No live bank or blockchain connection</span>
          <span><Icon name="gear" size={15} />R0 demo uses hand-set rules</span>
        </div>

        <section id="lp-engine" className="lp-section">
          <div className="lp-section-head">
            <div className="lp-kicker">What the engine helps you do</div>
            <h2>One case, three views of the money</h2>
          </div>
          <div className="lp-caps">
            {CAPABILITIES.map((c) => (
              <div key={c.title} className="lp-cap">
                <span className="ic"><Icon name={c.icon} size={22} /></span>
                <h3>{c.title}</h3>
                <p>{c.text}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="lp-cases" className="lp-section">
          <div className="lp-section-head">
            <div className="lp-kicker">Demo cases</div>
            <h2>Four cases, one question: what can the evidence support?</h2>
            <p>Start with the two headline cases: one payment at an innocent shop, and a whole day of a mule network. The two cases below replay the merchant story with one thing changed, a missing reference or a late report. Times are simulated (1 Oct, Bangkok time).</p>
          </div>
          <div className="lp-cases">
            {CASES.map((c, i) => (
              <article key={c.id} className={`lp-case ${i === 0 ? 'featured' : ''} ${c.id === 'network_day' ? 'scale' : ''}`}>
                <div className="lp-case-top">
                  <span className={`lp-badge ${i === 0 ? '' : c.id === 'network_day' ? 'scale' : 'muted'}`}>{c.badge}</span>
                  <span className="lp-focus">Focus: {c.focus}</span>
                </div>
                <h3>{c.title}</h3>
                <code>{c.id}</code>
                <p className="lp-short">{c.short}</p>
                <div className="lp-stats">
                  {c.stats.map(([v, l, tone]) => <div key={l}><b className={tone}>{v}</b><span>{l}</span></div>)}
                </div>
                <div className={`lp-more ${open[c.id] ? 'open' : ''}`} id={`lp-more-${c.id}`}>
                  <div className="lp-more-inner">
                    <p className="lp-summary">{c.summary}</p>
                    <div className="lp-story-label">What happens</div>
                    <ol className="lp-story">
                      {c.story.map(([t, txt]) => <li key={t + txt}><span className="t">{t}</span><span>{txt}</span></li>)}
                    </ol>
                    <div className="lp-try"><Icon name="bolt" size={16} /><div><b>Try this</b>{c.tryThis}</div></div>
                  </div>
                </div>
                <button className="lp-toggle" onClick={() => toggle(c.id)} aria-expanded={!!open[c.id]} aria-controls={`lp-more-${c.id}`}>
                  {open[c.id] ? 'Hide details' : 'Show details'}<Icon name="chevronDown" size={16} />
                </button>
                <button className={`lp-btn ${i === 0 ? 'primary' : 'outline'} block`} onClick={() => onStart(c.id, 'live', c.page)}>
                  Run this case<span className="lp-opens">opens {c.pageLabel}</span><Icon name="arrowRight" size={16} />
                </button>
              </article>
            ))}
          </div>
        </section>

        <section id="lp-how" className="lp-section">
          <div className="lp-section-head">
            <div className="lp-kicker">How to use the demo</div>
            <h2>Choose a case and mode, then follow the review</h2>
          </div>
          <div className="lp-how">
            <div className="lp-setup">
              <label>
                <span>Scenario</span>
                <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
                  {(scenarios.length ? scenarios : [{ id: scenario }]).map((s) => <option key={s.id} value={s.id}>{s.id}</option>)}
                </select>
              </label>
              <label>
                <span>Mode</span>
                <select value={mode} onChange={(e) => setMode(e.target.value as 'live' | 'recorded')}>
                  <option value="live">Live inference</option>
                  <option value="recorded" disabled={!recAvailable}>Recorded replay{recAvailable ? '' : ' (unavailable)'}</option>
                </select>
              </label>
              <button className="lp-btn primary" onClick={() => onStart(scenario, mode, pageFor(scenario))}>
                <Icon name="play" size={14} />Start run
              </button>
              <p className="lp-setup-note"><b>Live</b> submits evidence and officer decisions. <b>Replay</b> shows read-only saved states, when available.</p>
            </div>
            <ol className="lp-steps">
              {STEPS.map((s, i) => (
                <li key={s.title}>
                  <span className="n">0{i + 1}</span>
                  <div><b>{s.title}</b><p>{s.text}</p></div>
                </li>
              ))}
            </ol>
          </div>
          <div className="lp-guard">
            <Icon name="info" size={18} />
            Submitting evidence never releases funds automatically. Balances change only after an acknowledged officer decision.
          </div>
          <div className="lp-keys">
            <span className="lbl">Keyboard</span>
            {KEYS.map(([k, l]) => <span key={k}><kbd>{k}</kbd>{l}</span>)}
          </div>
        </section>
      </div>

      <footer className="lp-footer">
        <span><b>ทางเชื่อม</b> · Bank × Crypto Risk Graph</span>
        <span>Prototype · Synthetic data · NITMX Fintech Bootcamp 2026</span>
      </footer>
    </div>
  )
}
