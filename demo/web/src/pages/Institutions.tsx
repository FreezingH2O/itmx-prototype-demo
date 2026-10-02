import { useEffect, useState, type ReactNode } from 'react'
import { api, newKey, type Json } from '../api'
import { ACTION_LABEL, SHORT_ACTION, hm, instName, money, recStatus, shortId, thb, time, usdt } from '../format'
import { Icon } from '../icons'
import { useViews } from '../useRun'
import { t } from '../i18n'

type Props = { run: Json; version: number; present: boolean; compact?: boolean }
type Org = string
type Sel = { org: Org; seq: number } | null
const DEFAULT_ORGS: Org[] = ['bank_a', 'bank_b', 'exchange']
const NAME = instName
// Large scenarios: how many cards a panel shows before pointing to the full view.
const PANEL_LIMIT = 3

export default function Institutions({ run, version, present, compact }: Props) {
  const orgs: Org[] = run.institutions ?? DEFAULT_ORGS
  const large = !!run.large
  const fetched = useViews<Json>(orgs.map((o) => `/v1/runs/${run.run_id}/views/${o}`), version)
  const views: Record<Org, Json> = Object.fromEntries(orgs.map((o) => [o, fetched[`/v1/runs/${run.run_id}/views/${o}`]]))
  const [sel, setSel] = useState<Sel>(null)
  const [expanded, setExpanded] = useState<Org | null>(null)

  // Default inspector selection: the most recent event the engine scored.
  const fallback = latestScored(views, orgs)
  const active = sel ?? fallback
  const pick = (org: Org) => (seq: number) => setSel({ org, seq })
  const panelProps = (org: Org) => ({ org, data: views[org], run, present, sel: active, onSelect: pick(org), onExpand: () => setExpanded(org), limit: large ? PANEL_LIMIT : undefined })

  return (
    <div className="page">
      {!compact && (
        <div className="page-head">
          <div>
            <div className="page-title"><h1>{t('Institutions')}</h1><span className="tag lg">{t('Simulated clients')}</span></div>
            <p>{t('Recommendations inform officers. Only acknowledged decisions change balances.')}</p>
          </div>
        </div>
      )}
      {large && !compact && <Workload orgs={orgs} views={views} run={run} />}
      <div className="grid cols-3">
        {large
          ? orgs.map((o) => o === 'exchange' ? <ExchangePanel key={o} {...panelProps(o)} /> : <BankBPanel key={o} {...panelProps(o)} />)
          : <>
            <BankAPanel {...panelProps('bank_a')} />
            <BankBPanel {...panelProps('bank_b')} />
            <ExchangePanel {...panelProps('exchange')} />
          </>}
      </div>
      {!compact && <div className="card" style={{ marginTop: 16 }}><Inspector views={views} sel={active} present={present} /></div>}
      {!compact && <div className="foot-note">{t('Prototype design · Synthetic data')}</div>}
      {expanded && views[expanded] && (
        <Expanded org={expanded} data={views[expanded]} views={views} orgs={orgs} run={run} present={present}
          sel={active?.org === expanded ? active : null} onSelect={pick(expanded)} onClose={() => setExpanded(null)} />
      )}
    </div>
  )
}

function latestScored(views: Record<Org, Json>, orgs: Org[]): Sel {
  let best: { org: Org; seq: number; t: string } | null = null
  for (const o of orgs) {
    for (const f of views[o]?.feed ?? []) {
      if (!f.assessment_id) continue
      if (!best || f.sim_time >= best.t) best = { org: o, seq: f.seq, t: f.sim_time }
    }
  }
  return best ? { org: best.org, seq: best.seq } : null
}

// Large scenarios: officer workload across every institution, the point of the scale demo.
function Workload({ orgs, views, run }: { orgs: Org[]; views: Record<Org, Json>; run: Json }) {
  const waiting = (o: Org) => live(views[o]?.recommendations ?? []).filter((r) => canAct(r, run) && r.action_type !== 'EXISTING_CONTROLS_ONLY').length
  const total = orgs.reduce((s, o) => s + waiting(o), 0)
  return (
    <div className="stat-row" style={{ marginBottom: 16 }}>
      <div className="stat"><span className="lbl">{t('Awaiting an officer')}</span><b className={total ? 'amber' : ''}>{total}</b></div>
      {orgs.map((o) => <div key={o} className="stat"><span className="lbl">{NAME(o)}</span><b>{waiting(o)}</b></div>)}
    </div>
  )
}

/* ---------------- shared pieces */

type PanelProps = { org: Org; data: Json; run: Json; present: boolean; sel: Sel; onSelect: (seq: number) => void; onExpand: () => void; limit?: number }

function More({ n, onExpand }: { n: number; onExpand: () => void }) {
  return n > 0 ? <button className="ghost small" onClick={onExpand} style={{ marginTop: 6 }}>{t('+{n} more in full view', { n })}</button> : null
}

function PanelHead({ org, onExpand }: { org: Org; onExpand: () => void }) {
  return (
    <div className="inst-head">
      <span className="inst-ico"><Icon name="bank" size={24} /></span>
      <span className="inst-name">{NAME(org)}</span>
      <span className="tag">{t('Simulated client')}</span>
      <span className="grow" />
      <button className="icon-btn" onClick={onExpand} title={t('Open {n} full view', { n: NAME(org) })} aria-label={t('Expand {n}', { n: NAME(org) })}>
        <Icon name="expand" size={17} />
      </button>
    </div>
  )
}

// Feed summaries come from the simulated client; split them into from / to / amount for the table.
function parseFeed(f: Json): { from: string; to: string; amount: string } {
  const s: string = f.summary ?? ''
  const amt = (v: string) => `฿${v.replace(/\.00$/, '')}`
  let m = s.match(/^transfer ([\d,.]+) THB (\S+) -> (\S+)/)
  if (m) return { from: m[2], to: m[3], amount: amt(m[1]) }
  m = s.match(/^deposit credit ([\d,.]+) THB to (\S+)/)
  if (m) return { from: t('THB deposit'), to: m[2], amount: amt(m[1]) }
  m = s.match(/^trade ([\d,.]+) THB -> ([\d.]+) USDT \((\S+)\)/)
  if (m) return { from: t('{c} buys USDT', { c: m[3] }), to: '', amount: `${Number(m[2]).toFixed(2)} USDT` }
  m = s.match(/^withdrawal request (\S+) ([\d,.]+) (\w+)/)
  if (m) return { from: t('Withdrawal {id}', { id: m[1] }), to: '', amount: `${m[2].replace(/\.00$/, '')} ${m[3]}` }
  return { from: s, to: '', amount: '' }
}

function FeedTable({ feed, org, sel, onSelect, limit }: { feed: Json[]; org: Org; sel: Sel; onSelect: (seq: number) => void; limit?: number }) {
  if (!feed.length) return <div className="empty">{t('Nothing sent yet. Press Play or Step.')}</div>
  const rows = limit ? feed.slice(-limit) : feed
  return (
    <table className="data">
      <thead><tr><th>{t('Time')}</th><th>{t('From → To')}</th><th className="r">{t('Amount')}</th></tr></thead>
      <tbody>
        {rows.map((f) => {
          const p = parseFeed(f)
          return (
            <tr key={f.seq} className={`click ${sel?.org === org && sel.seq === f.seq ? 'sel' : ''}`} onClick={() => onSelect(f.seq)}>
              <td className="num">{hm(f.sim_time)}</td>
              <td>{p.to ? <>{p.from} → {p.to}</> : p.from}</td>
              <td className="r">{p.amount}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function actionsFor(rec: Json): { action: string; label: string; scope?: Json; primary?: boolean }[] {
  const st = rec.subject_state ?? {}
  const rid = rec.target_scope?.restriction_id
  if (st.kind === 'withdrawal') {
    if (st.state === 'held_for_review') return [{ action: 'release_withdrawal', label: t('Release withdrawal') }]
    if (rec.action_type === 'RECOMMEND_RESTRICTION_REVIEW') return [
      { action: 'hold_withdrawal', label: t('Hold withdrawal'), primary: true },
      { action: 'no_action', label: t('No action') }]
    return [{ action: 'acknowledge', label: t('Acknowledge') }]
  }
  if (rec.action_type === 'RECOMMEND_RESTRICTION_REVIEW' && st.kind === 'account') return [
    { action: 'restrict_amount', label: t('Restrict {amt} only', { amt: thb(rec.target_scope.amount_minor) }), scope: { amount_minor: rec.target_scope.amount_minor }, primary: true },
    { action: 'no_action', label: t('No action') }]
  if (rid) return [
    { action: 'release_restriction', label: t('Release this hold'), scope: { restriction_id: rid }, primary: rec.action_type === 'RECOMMEND_RELEASE_REVIEW' },
    { action: 'retain_restriction', label: t('Keep hold'), scope: { restriction_id: rid } },
    { action: 'request_information', label: t('Request more info'), scope: { restriction_id: rid } }]
  return [{ action: 'acknowledge', label: t('Acknowledge') }]
}

function canAct(rec: Json, run: Json): boolean {
  const decided = rec.decisions.some((d: Json) => d.outcome === 'acknowledged')
  const withdrawalHeld = rec.subject_state?.kind === 'withdrawal' && rec.subject_state.state === 'held_for_review'
  return run.mode !== 'recorded' && rec.status !== 'superseded' && (!decided || withdrawalHeld) && rec.subject_state?.state !== 'broadcast'
}

function useDecide(rec: Json, org: Org, run: Json) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function decide(action: string, scope: Json = {}, reason = 'Reviewed evidence pack') {
    setBusy(true); setErr(null)
    try {
      await api.post(`/v1/runs/${run.run_id}/decisions`, {
        recommendation_id: rec.recommendation_id, actor_org: org, actor_id: `${org}-officer-1`, action,
        target_scope: scope, reason, expected_state_version: rec.subject_state.state_version, idempotency_key: newKey(),
      }, { 'X-Sim-Role': org })
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return { busy, err, decide }
}

function ActionButtons({ rec, org, run, reason, extra }: { rec: Json; org: Org; run: Json; reason?: string; extra?: ReactNode }) {
  const { busy, err, decide } = useDecide(rec, org, run)
  if (!canAct(rec, run)) return run.mode === 'recorded' ? <div className="xs muted" style={{ marginTop: 8 }}>{t('Recorded replay: decisions are read-only.')}</div> : null
  const acts = actionsFor(rec)
  return (
    <>
      <div className={extra ? 'btn-grid' : 'btn-row stretch'}>
        {extra}
        {acts.map((a) => (
          <button key={a.action} className={a.primary ? 'primary' : a.action === 'release_withdrawal' ? 'outline' : ''} disabled={busy}
            onClick={() => decide(a.action, a.scope, reason)}>{a.label}</button>
        ))}
      </div>
      {err && <div className="callout bad"><Icon name="alert" size={16} />{err}</div>}
    </>
  )
}

function keyLine(rec: Json): string {
  const st = rec.subject_state ?? {}
  if (rec.action_type === 'RECOMMEND_RESTRICTION_REVIEW' && st.kind === 'account' && rec.target_scope.amount_minor !== undefined)
    return t('Traced amount remaining: {amt}', { amt: thb(rec.target_scope.amount_minor) })
  return rec.rationale?.[0] ?? ''
}

// Compact inbox card: what, status, one line of why, the officer's buttons.
function RecCard({ rec, org, run, onExpand }: { rec: Json; org: Org; run: Json; onExpand: () => void }) {
  const [label, tone] = recStatus(rec.status)
  const last = rec.decisions[rec.decisions.length - 1]
  return (
    <div className="box">
      <div className="row">
        <b>{shortId(rec.subject_id)} · {t(SHORT_ACTION[rec.action_type] ?? rec.action_type)}</b>
        <span className={`pill ${tone}`}>{label}</span>
      </div>
      <div className="small" style={{ marginTop: 6, color: 'var(--text-2)' }}>{keyLine(rec)}</div>
      {last && <div className="xs muted" style={{ marginTop: 6 }}>{t('Officer')}: {t(last.action.replace(/_/g, ' '))} → {t(last.outcome)}</div>}
      <ActionButtons rec={rec} org={org} run={run} extra={canAct(rec, run) ? <button onClick={onExpand}>{t('Review evidence')}</button> : null} />
    </div>
  )
}

function LinkCards({ recs, onExpand }: { recs: Json[]; onExpand: () => void }) {
  if (!recs.length) return null
  return (
    <div className="link-grid">
      {recs.map((r) => (
        <button key={r.recommendation_id} className="link-card" onClick={onExpand}>
          <span className="l"><Icon name="file" size={16} />{shortId(r.subject_id)} · {t(SHORT_ACTION[r.action_type] ?? r.action_type)}</span>
          <Icon name="chevronRight" size={16} />
        </button>
      ))}
    </div>
  )
}

const isMain = (r: Json) => r.action_type === 'RECOMMEND_RESTRICTION_REVIEW' || r.action_type === 'RECOMMEND_RELEASE_REVIEW'
const live = (recs: Json[]) => recs.filter((r) => r.status !== 'superseded')

/* ---------------- Bank A */

function BankAPanel({ org, data, run, sel, onSelect, onExpand }: PanelProps) {
  if (!data) return <div className="card"><PanelHead org={org} onExpand={onExpand} /><div className="empty">{t('Loading…')}</div></div>
  const recs = live(data.recommendations)
  const pending = recs.some((r) => canAct(r, run))
  return (
    <div className={`card inst-col ${pending ? 'focus' : ''}`}>
      <PanelHead org={org} onExpand={onExpand} />
      <div className="box">
        <div className="card-head" style={{ marginBottom: 8 }}>
          <span className="card-title"><span className="ico"><Icon name="file" /></span>{t('Transaction feed')}</span>
          <span className="xs muted" style={{ display: 'flex', alignItems: 'center', gap: 6 }}><span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--good)' }} />{t('Sent to Engine API')}</span>
        </div>
        <FeedTable feed={data.feed} org={org} sel={sel} onSelect={onSelect} limit={5} />
      </div>
      <div>
        <div className="card-title" style={{ margin: '4px 0 10px' }}><span className="ico"><Icon name="file" /></span>{t('Recommendation inbox')}</div>
        {recs.length === 0 ? <div className="empty">{t('No recommendations yet.')}</div>
          : <div className="stack">{recs.map((r) => <RecCard key={r.recommendation_id} rec={r} org={org} run={run} onExpand={onExpand} />)}</div>}
      </div>
    </div>
  )
}

/* ---------------- Bank B */

function BankBPanel({ org, data, run, sel, onSelect, onExpand, limit }: PanelProps) {
  if (!data) return <div className="card"><PanelHead org={org} onExpand={onExpand} /><div className="empty">{t('Loading…')}</div></div>
  const recs = live(data.recommendations)
  const queue = data.review_queue.filter((q: Json) => q.status === 'active' || q.review_state !== 'released')
  const lastQ = queue.length ? queue : data.review_queue.slice(-1)
  const inQueue = new Set(lastQ.map((q: Json) => q.account_id))
  // Main actionable recommendations not already covered by a review-queue card.
  const main = recs.filter((r) => isMain(r) && !inQueue.has(r.subject_id) && canAct(r, run))
  const others = recs.filter((r) => !main.includes(r) && !(inQueue.has(r.subject_id)))
  const pending = lastQ.length > 0 || main.length > 0
  const cap = <T,>(xs: T[], n = limit) => (n === undefined ? xs : xs.slice(0, n))
  const hidden = limit === undefined ? 0 : Math.max(0, lastQ.length - 1) + Math.max(0, main.length - limit) + Math.max(0, others.length - limit * 2)
  return (
    <div className={`card inst-col ${pending ? 'focus' : ''}`}>
      <PanelHead org={org} onExpand={onExpand} />
      {cap(lastQ, limit === undefined ? undefined : 1).map((q: Json) => <ReviewCard key={q.restriction_id} q={q} data={data} org={org} run={run} />)}
      {cap(main).map((r) => <RecCard key={r.recommendation_id} rec={r} org={org} run={run} onExpand={onExpand} />)}
      {!pending && (
        <div className="box">
          <div className="card-title" style={{ marginBottom: 6 }}><span className="ico"><Icon name="list" /></span>{t('Review queue')}</div>
          <div className="empty">{t('No restriction under review.')}</div>
        </div>
      )}
      <LinkCards recs={cap(others, limit === undefined ? undefined : limit * 2)} onExpand={onExpand} />
      <More n={hidden} onExpand={onExpand} />
      {!pending && !others.length && (
        <div className="box">
          <div className="card-title" style={{ marginBottom: 8 }}><span className="ico"><Icon name="file" /></span>{t('Transaction feed')}</div>
          <FeedTable feed={data.feed} org={org} sel={sel} onSelect={onSelect} limit={4} />
        </div>
      )}
    </div>
  )
}

const HIST_LABEL: Record<string, string> = {
  restricted: 'Officer placed hold',
  review_pending: 'Evidence received · Review pending',
  more_info_requested: 'More information requested',
  retained: 'Officer kept hold',
  released: 'Hold released',
}

function ReviewCard({ q, data, org, run }: { q: Json; data: Json; org: Org; run: Json }) {
  const [reason, setReason] = useState(() => t('Reviewed evidence pack'))
  const acct = data.accounts.find((a: Json) => a.account_id === q.account_id)
  const rec = [...data.recommendations].reverse().find((r: Json) => r.target_scope?.restriction_id === q.restriction_id && r.status !== 'superseded')
  const sub = q.submissions[q.submissions.length - 1]
  const released = q.review_state === 'released'
  return (
    <div className="box">
      <div className="row" style={{ marginBottom: 10 }}>
        <span className="card-title"><span className="ico"><Icon name="list" /></span>{t('Review queue')}</span>
        <span className={`pill ${released ? 'good' : 'amber'}`}>{t(q.review_state.replace(/_/g, ' '))}</span>
      </div>
      <b>{t(acct?.holder_kind === 'merchant' ? 'Merchant' : 'Account')} · {shortId(q.account_id)}</b>
      <div className="money3">
        <div><span className="lbl">{t('Total')}</span><b>{thb(q.ledger.total_minor)}</b></div>
        <div><span className="lbl">{t('Usable')}</span><b>{thb(q.ledger.available_minor)}</b></div>
        <div><span className="lbl">{t('Held')}</span><b className={q.ledger.restricted_minor ? 'amber' : ''}>{thb(q.ledger.restricted_minor)}</b></div>
      </div>
      {sub ? <>
        <div className="doc-line"><Icon name="file" size={18} />
          <div><b>{t('Evidence')} {sub.submission_id}</b>
            <div className="small muted">{sub.consistency.consistent ? t('Receipt matches amount, time and payer.') : t('Does not match: {x}', { x: sub.consistency.issues.join('; ') })}</div></div>
        </div>
        {!released && <div className="callout amber"><Icon name="alert" size={16} />{t('Consistency is not proof. Officer review required.')}</div>}
      </> : !released && <div className="small muted" style={{ marginTop: 10 }}>{t('Waiting for the account holder to send evidence.')}</div>}
      {rec && (
        <div className="row small" style={{ marginTop: 12 }}>
          <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}><Icon name="send" size={15} />{t('Recommendation')}</span>
          <b className="teal">{t(SHORT_ACTION[rec.action_type])} · {rec.recommendation_id}</b>
        </div>
      )}
      {rec && canAct(rec, run) && (
        <div style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
          <div className="row"><b>{t('Officer console')}</b><span className="xs muted">{t('Scope')}: <b className="amber">{t('{amt} only', { amt: thb(q.amount_minor) })}</b></span></div>
          <input type="text" value={reason} onChange={(e) => setReason(e.target.value)} aria-label={t('Decision reason')} style={{ width: '100%', marginTop: 8 }} />
          <ActionButtons rec={rec} org={org} run={run} reason={reason} />
        </div>
      )}
      <div style={{ marginTop: 12 }}>
        <span className="small" style={{ display: 'flex', gap: 8, alignItems: 'center', fontWeight: 600 }}><Icon name="clock" size={15} />{t('Audit trail')}</span>
        <ul className="timeline">
          {q.history.map((h: Json, i: number) => (
            <li key={i}><span className="t">{hm(h.at)}</span><span>{h.state === 'restricted' ? t('Officer placed {amt} hold', { amt: thb(q.amount_minor) }) : t(HIST_LABEL[h.state] ?? h.state)}</span></li>
          ))}
        </ul>
      </div>
    </div>
  )
}

/* ---------------- Exchange */

function depositRefs(data: Json): Record<string, string> {
  const refs: Record<string, string> = {}
  for (const l of data.api_log ?? []) {
    const evs = l.request?.events
    if (!Array.isArray(evs)) continue
    for (const e of evs) if (e.event_type === 'exchange_deposit' && e.reference_id) refs[e.to_ref] = e.reference_id
  }
  return refs
}

function verifiedCustomers(data: Json): Set<string> {
  const out = new Set<string>()
  for (const r of data.recommendations ?? []) for (const e of r.evidence ?? []) {
    if (e.kind !== 'link_verified') continue
    const m = (e.text as string).match(/X-\d+/)
    if (m) out.add(m[0])
  }
  return out
}

const WD_STATE: Record<string, [string, string]> = {
  requested: ['Pending', 'teal'],
  pending: ['Pending review', 'teal'],
  held_for_review: ['Held for review', 'amber'],
  released: ['Released', 'good'],
  broadcast: ['Broadcast on chain', 'bad'],
}

function ExchangePanel({ org, data, run, onExpand, limit }: PanelProps) {
  if (!data) return <div className="card"><PanelHead org={org} onExpand={onExpand} /><div className="empty">{t('Loading…')}</div></div>
  const recs = live(data.recommendations)
  const wd = data.withdrawals[data.withdrawals.length - 1]
  const wdRec = wd && [...recs].reverse().find((r) => r.subject_state?.kind === 'withdrawal')
  const others = recs.filter((r) => r !== wdRec)
  const refs = depositRefs(data)
  const verified = verifiedCustomers(data)
  const allDeposits = data.feed.filter((f: Json) => f.summary?.startsWith('deposit'))
  const deposits = limit === undefined ? allDeposits : allDeposits.slice(-limit * 2)
  const pending = !!(wdRec && canAct(wdRec, run))
  const wdDecisions = data.decisions.filter((d: Json) => wdRec && d.recommendation_id === wdRec.recommendation_id)
  return (
    <div className={`card inst-col ${pending ? 'focus' : ''}`}>
      <PanelHead org={org} onExpand={onExpand} />
      <div className="box">
        {!wd ? <>
          <div className="card-title"><span className="ico"><Icon name="list" /></span>{t('Withdrawals')}</div>
          <div className="empty">{t('No withdrawal request yet.')}</div>
        </> : <>
          <div className="card-title"><span className="ico"><Icon name="list" /></span>{t('Withdrawal {id}', { id: shortId(wd.withdrawal_id) })}</div>
          <div className="row" style={{ marginTop: 10 }}>
            <span className="big-amt">{usdt(wd.amount_minor).replace('.00 ', ' ')}</span>
            <span className={`pill ${WD_STATE[wd.state]?.[1] ?? ''}`}>{t(WD_STATE[wd.state]?.[0] ?? wd.state)}</span>
          </div>
          <div className="muted" style={{ marginBottom: 10 }}>{t('Customer')} {shortId(wd.customer_id)} · {wd.chain.toUpperCase()}</div>
          <div className="deadline"><Icon name="clock" size={17} /><span className="grow">{t('Control deadline')}</span><b className="teal">{hm(wd.controllable_until)}</b></div>
          {refs[wd.customer_id] && <div className="deadline"><Icon name="file" size={17} /><span className="grow">{t(verified.has(shortId(wd.customer_id)) ? 'Verified deposit reference' : 'Deposit reference')}</span><span>{refs[wd.customer_id]}</span></div>}
          <ul className="timeline" style={{ marginTop: 10 }}>
            <li><span className="t">{hm(wd.requested_at)}</span><span>{t('Request received')}</span></li>
            {wdDecisions.map((d: Json) => <li key={d.decision_id}><span className="t">{hm(d.recorded_at)}</span><span>{t('Officer')} {t(d.action.replace(/_/g, ' '))} {t(d.outcome)}</span></li>)}
            {wd.state === 'broadcast' && <li><span className="t">-</span><span>{t('Broadcast on chain (no longer controllable)')}</span></li>}
          </ul>
          {wdRec && <ActionButtons rec={wdRec} org={org} run={run} />}
          {pending && <div className="xs amber" style={{ textAlign: 'center', marginTop: 8 }}>{t('Officer decision required')}</div>}
        </>}
      </div>
      <div className="box">
        <div className="card-title" style={{ marginBottom: 10 }}><span className="ico"><Icon name="list" /></span>{t('Deposit feed')}</div>
        {deposits.length === 0 ? <div className="empty">{t('No deposits yet.')}</div> : deposits.map((f: Json) => {
          const p = parseFeed(f)
          const ok = verified.has(p.to)
          return (
            <div key={f.seq} className="feed-ok">
              {ok ? <Icon name="checkCircle" size={20} /> : <Icon name="clock" size={20} />}
              <span>{p.to} · {p.amount} · {t(ok ? 'Verified' : 'Sent')}</span>
            </div>
          )
        })}
      </div>
      <LinkCards recs={limit === undefined ? others : others.slice(-limit * 2)} onExpand={onExpand} />
      {limit !== undefined && <More n={Math.max(0, others.length - limit * 2) + Math.max(0, allDeposits.length - deposits.length)} onExpand={onExpand} />}
    </div>
  )
}

/* ---------------- API call inspector */

function findCalls(log: Json[], entry: Json) {
  const sid = entry.event_id?.split(':').pop()
  const posted = log.find((l) => Array.isArray(l.request?.events) && l.request.events.some((e: Json) => e.source_event_id === sid))
  const event = posted?.request.events.find((e: Json) => e.source_event_id === sid)
  const result = posted?.response?.results?.find((r: Json) => r.source_event_id === sid)
  const assess = log.find((l) => l.path.endsWith('/assessments') && (l.request?.subject_id === entry.subject_id || l.request?.subject_id === entry.event_id))
  return { posted, event, result, assess }
}

function Inspector({ views, sel, present }: { views: Record<Org, Json>; sel: Sel; present: boolean }) {
  const [showJson, setShowJson] = useState(false)
  const data = sel ? views[sel.org] : null
  const entry = data?.feed.find((f: Json) => f.seq === sel?.seq)
  const head = (
    <div className="card-head" style={{ flexWrap: 'wrap' }}>
      <span className="card-title">
        <span className="inst-ico" style={{ width: 36, height: 36, borderRadius: 8, background: 'var(--navy-2)', color: '#5fd6cf' }}><Icon name="code" /></span>
        <span className="caps">{t('API call inspector')}</span>
        {entry && <span className="small muted" style={{ fontWeight: 400 }}>{t('Selected event')} <b style={{ color: 'var(--text)' }}>{shortId(entry.event_id ?? '')} · {parseFeed(entry).to ? `${parseFeed(entry).from} → ${parseFeed(entry).to}` : parseFeed(entry).from}</b></span>}
      </span>
      <span style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        {entry && !present && <button onClick={() => setShowJson(!showJson)} style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><Icon name="code" size={15} />{t(showJson ? 'Hide JSON' : 'View JSON')}</button>}
        <span className="xs muted">{t('Transaction ranking score, not a probability.')}</span>
      </span>
    </div>
  )
  if (!entry || !data) return <>{head}<div className="empty">{t('Click any transaction row to see the call it made to the Engine API.')}</div></>
  const { posted, event, result, assess } = findCalls(data.api_log, entry)
  const res = assess?.response
  const recs = data.recommendations ?? []
  const decisions = data.decisions ?? []
  const steps = [
    { label: t('Evidence'), icon: 'file', on: true, cls: '' },
    { label: t('Recommendation'), icon: 'graph', on: recs.length > 0, cls: 'teal' },
    { label: t('Officer decision'), icon: 'user', on: decisions.length > 0, cls: 'amber' },
    { label: t('Ledger update'), icon: 'database', on: decisions.some((d: Json) => d.outcome === 'acknowledged'), cls: 'navy' },
  ]
  const p = parseFeed(entry)
  return (
    <>
      {head}
      <div className="inspector">
        <div className="pane">
          <h4>{t('Request')} · <span style={{ fontWeight: 500 }}>{event?.event_type?.endsWith('transfer') ? t('Assess {amt} transfer', { amt: p.amount }) : t((event?.event_type ?? 'event').replace(/_/g, ' '))}</span></h4>
          <dl className="kv">
            <dt>{t('Event')}</dt><dd>{event?.source_event_id ?? shortId(entry.event_id ?? '')}</dd>
            {event?.from_ref && <><dt>{t('From')}</dt><dd>{shortId(event.from_ref)}</dd></>}
            {event?.to_ref && <><dt>{t('To')}</dt><dd>{shortId(event.to_ref)}</dd></>}
            <dt>{t('Occurred')}</dt><dd>{time(event?.occurred_at)}</dd>
            <dt>{t('Available')}</dt><dd>{time(event?.available_at ?? entry.sim_time)}</dd>
          </dl>
        </div>
        <div className="pane">
          <h4>{t('Response')} · <span className={result?.status === 'accepted' || assess ? 'good' : 'amber'}>{assess ? t('Assessed') : t(result?.status ?? entry.status)}</span></h4>
          <dl className="kv">
            {res ? <>
              <dt>{t('Ranking score')}</dt><dd><b>{res.risk_score === null ? t('not scored ({s})', { s: t(res.score_status.replace(/_/g, ' ')) }) : res.risk_score.toFixed(2)}</b></dd>
              <dt>{t('Case')}</dt><dd>{res.case_id ?? t('none')}</dd>
              <dt>{t('Recommendations')}</dt><dd>{res.recommendations.length ? res.recommendations.map((r: Json) => `${r.id} ${t(SHORT_ACTION[r.action_type] ?? '')}`).join(', ') : t('none')}</dd>
            </> : <><dt>{t('Assessment')}</dt><dd>{t('not requested for this event type')}</dd></>}
            {event?.reference_id && <><dt>{t('Reference')}</dt><dd>{event.reference_id}</dd></>}
            <dt>{t('Latency')}</dt><dd>{[posted?.latency_ms, assess?.latency_ms].filter((v) => v !== undefined).map((v) => `${v} ms`).join(' + ') || '-'}</dd>
          </dl>
        </div>
        <div className="flow">
          {steps.map((s, i) => (
            <div key={s.label} style={{ display: 'contents' }}>
              {i > 0 && <span className="arrow">⟶</span>}
              <div className="step"><span className={`dot ${s.on ? s.cls : 'off'}`}><Icon name={s.icon} size={24} /></span>{s.label}</div>
            </div>
          ))}
        </div>
      </div>
      {showJson && <pre className="json">{JSON.stringify([posted, assess].filter(Boolean), null, 2)}</pre>}
    </>
  )
}

/* ---------------- Full-screen institution view */

function Expanded({ org, data, views, run, present, sel, onSelect, onClose }: {
  org: Org; data: Json; views: Record<Org, Json>; orgs: Org[]; run: Json; present: boolean; sel: Sel; onSelect: (seq: number) => void; onClose: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = '' }
  }, [onClose])
  const recs = [...data.recommendations].reverse()
  const open = recs.filter((r) => canAct(r, run)).length
  const lastSeq = data.feed.length ? data.feed[data.feed.length - 1].seq : null
  const inspect: Sel = sel ?? (lastSeq !== null ? { org, seq: lastSeq } : null)
  const restricted = data.accounts.reduce((s: number, a: Json) => s + (a.ledger?.restricted_minor ?? 0), 0)
  const stats = org === 'exchange'
    ? [[t('Customers'), data.customers.length], [t('Withdrawals'), data.withdrawals.length], [t('Awaiting officer'), open], [t('Decisions recorded'), data.decisions.length]]
    : [[t('Accounts'), data.accounts.length], [t('Amount held'), thb(restricted)], [t('Awaiting officer'), open], [t('Decisions recorded'), data.decisions.length]]
  return (
    <div className="overlay" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()} role="dialog" aria-label={t('{n} full view', { n: NAME(org) })}>
        <div className="sheet-head">
          <span className="inst-ico"><Icon name="bank" size={24} /></span>
          <span className="inst-name">{NAME(org)}</span>
          <span className="tag">{t('Simulated client')}</span>
          <span className="sub">{t("Everything this institution's system sees and sent at {at}", { at: time(run.clock.now) })}</span>
          <span className="grow" />
          <button className="icon-btn" onClick={onClose} aria-label={t('Close full view')} title={`${t('Close')} (Esc)`}><Icon name="close" size={20} /></button>
        </div>
        <div className="sheet-body">
          <div className="stat-row">
            {stats.map(([l, v]) => <div key={l as string} className="stat"><span className="lbl">{l}</span><b>{v}</b></div>)}
          </div>
          <div className="sheet-grid">
            <div className="stack">
              {org !== 'exchange' && data.review_queue.map((q: Json) => <ReviewCard key={q.restriction_id} q={q} data={data} org={org} run={run} />)}
              <div className="card">
                <div className="card-head"><span className="card-title"><span className="ico"><Icon name="file" /></span>{t('Recommendations')}</span><span className="sub">{t('{n} received', { n: recs.length })}</span></div>
                {recs.length === 0 ? <div className="empty">{t('No recommendations yet.')}</div> : recs.map((r) => <RecFull key={r.recommendation_id} rec={r} org={org} run={run} />)}
              </div>
            </div>
            <div className="stack">
              <Holdings org={org} data={data} />
              <div className="card">
                <div className="card-head"><span className="card-title"><span className="ico"><Icon name="file" /></span>{t('Transaction feed')}</span><span className="sub">{t('click a row to inspect its API call')}</span></div>
                <FeedTable feed={data.feed} org={org} sel={inspect} onSelect={onSelect} />
              </div>
              <div className="card"><Inspector views={views} sel={inspect} present={present} /></div>
              <div className="card">
                <div className="card-head"><span className="card-title"><span className="ico"><Icon name="code" /></span>{t('API calls')}</span><span className="sub">{t('{n} calls', { n: data.api_log.length })}</span></div>
                <table className="data">
                  <thead><tr><th>{t('Sim time')}</th><th>{t('Call')}</th><th>{t('Status')}</th><th className="r">{t('Latency')}</th></tr></thead>
                  <tbody>{[...data.api_log].reverse().map((l: Json) => (
                    <tr key={l.seq}><td className="num">{time(l.sim_time)}</td><td><code>{l.method} {l.path.replace(/\/v1\/runs\/[^/]+/, '')}</code></td>
                      <td><span className={`pill ${l.status_code < 300 ? 'good' : 'bad'}`}>{l.status_code}</span></td><td className="r">{l.latency_ms} ms</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function Holdings({ org, data }: { org: Org; data: Json }) {
  if (org === 'exchange') return (
    <div className="card">
      <div className="card-head"><span className="card-title"><span className="ico"><Icon name="wallet" /></span>{t('Customers and withdrawals')}</span></div>
      <table className="data">
        <thead><tr><th>{t('Customer')}</th><th className="r">THB</th><th className="r">USDT</th></tr></thead>
        <tbody>{data.customers.map((c: Json) => <tr key={c.customer_id}><td>{shortId(c.customer_id)}</td><td className="r">{thb(c.balances.THB)}</td><td className="r">{usdt(c.balances.USDT)}</td></tr>)}</tbody>
      </table>
      {data.withdrawals.length > 0 && <table className="data" style={{ marginTop: 12 }}>
        <thead><tr><th>{t('Withdrawal')}</th><th>{t('Customer')}</th><th className="r">{t('Amount')}</th><th>{t('State')}</th><th>{t('Deadline')}</th></tr></thead>
        <tbody>{data.withdrawals.map((w: Json) => <tr key={w.withdrawal_id}><td>{shortId(w.withdrawal_id)}</td><td>{shortId(w.customer_id)}</td><td className="r">{usdt(w.amount_minor)}</td>
          <td><span className={`pill ${WD_STATE[w.state]?.[1] ?? ''}`}>{t(WD_STATE[w.state]?.[0] ?? w.state)}</span></td><td>{hm(w.controllable_until)}</td></tr>)}</tbody>
      </table>}
    </div>
  )
  return (
    <div className="card">
      <div className="card-head"><span className="card-title"><span className="ico"><Icon name="wallet" /></span>{t("Accounts in this bank's ledger")}</span></div>
      <table className="data">
        <thead><tr><th>{t('Account')}</th><th>{t('Holder')}</th><th className="r">{t('Total')}</th><th className="r">{t('Held')}</th><th className="r">{t('Usable')}</th></tr></thead>
        <tbody>{data.accounts.map((a: Json) => (
          <tr key={a.account_id}><td>{shortId(a.account_id)}</td><td className="small">{a.holder_name}</td><td className="r">{thb(a.ledger.total_minor)}</td>
            <td className={`r ${a.ledger.restricted_minor ? 'amber' : ''}`}>{thb(a.ledger.restricted_minor)}</td><td className="r">{thb(a.ledger.available_minor)}</td></tr>
        ))}</tbody>
      </table>
    </div>
  )
}

function RecFull({ rec, org, run }: { rec: Json; org: Org; run: Json }) {
  const [reason, setReason] = useState(() => t('Reviewed evidence pack'))
  const [label, tone] = recStatus(rec.status)
  const st = rec.subject_state ?? {}
  return (
    <div className="rec-full" style={{ opacity: rec.status === 'superseded' ? 0.55 : 1 }}>
      <div className="row">
        <b>{rec.recommendation_id} · {t(ACTION_LABEL[rec.action_type])}</b>
        <span className={`pill ${tone}`}>{label}</span>
      </div>
      <div className="small muted" style={{ marginTop: 4 }}>
        {rec.subject_display}{rec.priority && <> · {t('priority')} {t(rec.priority)}</>}
        {rec.target_scope.amount_minor !== undefined && <> · {t('scope')} {money(rec.target_scope.amount_minor, rec.target_scope.asset)}</>}
        {rec.expires_at && <> · {t('deadline')} {time(rec.expires_at)}</>}
      </div>
      {st.kind === 'account' && <div className="small" style={{ marginTop: 6 }}>{t('Your system: total {a} · held {b} · usable {c}', { a: thb(st.total_minor), b: thb(st.restricted_minor), c: thb(st.available_minor) })}</div>}
      {st.kind === 'withdrawal' && <div className="small" style={{ marginTop: 6 }}>{t('Your system: withdrawal {s}', { s: t(st.state.replace(/_/g, ' ')) })}</div>}
      <div className="section-label">{t('Why')}</div>
      <ul style={{ marginTop: 0 }}>{rec.rationale.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
      <div className="section-label">{t('Evidence')} ({rec.evidence.length})</div>
      <ul style={{ marginTop: 0 }}>{rec.evidence.map((e: Json, i: number) => <li key={i}><span className="ev-kind">{e.kind.replace(/_/g, ' ')}</span>{e.text}</li>)}</ul>
      {rec.decisions.length > 0 && <>
        <div className="section-label">{t('Officer decisions')}</div>
        <ul style={{ marginTop: 0 }}>{rec.decisions.map((d: Json) => <li key={d.decision_id ?? d.idempotency_key}>{hm(d.recorded_at)} · {t(d.action.replace(/_/g, ' '))} → <b>{t(d.outcome)}</b> ({d.outcome_detail})</li>)}</ul>
      </>}
      {canAct(rec, run) && <input type="text" value={reason} onChange={(e) => setReason(e.target.value)} aria-label={t('Decision reason')} style={{ width: '100%', marginTop: 10 }} />}
      <ActionButtons rec={rec} org={org} run={run} reason={reason} />
    </div>
  )
}
