import { Fragment, useState } from 'react'
import { api, type Json } from '../api'
import { SHORT_ACTION, hm, instName, recStatus, shortId, thb, time, usdt } from '../format'
import { Icon } from '../icons'
import { useView } from '../useRun'
import GraphView, { type GraphSel } from './GraphView'

type Props = { run: Json; version: number; present: boolean; compact?: boolean }
const INST = (org: string): [string, string] => [instName(org), org === 'exchange' ? 'swap' : 'bank']
const LIST_LIMIT = 6   // side-card rows before "+N more" (network cases list every account)

export default function EnginePage({ run, version, present, compact }: Props) {
  const [caseId, setCaseId] = useState<string>('')
  const [focus, setFocus] = useState<string>('')
  const q = (ps: Record<string, string>) => { const s = new URLSearchParams(Object.entries(ps).filter(([, v]) => v)).toString(); return s ? `?${s}` : '' }
  const { data: graph } = useView<Json>(`/v1/runs/${run.run_id}/graph${q({ case_id: caseId, focus })}`, version)
  const { data: view } = useView<Json>(`/v1/runs/${run.run_id}/views/simulator${q({ case_id: caseId })}`, version)
  const [sel, setSel] = useState<GraphSel>(null)
  const assessment = view?.cases?.[0]?.assessment
  const openCases: Json[] = (view?.cases ?? []).filter((c: Json) => c.status === 'open')
  const model = view?.model_info
  const down = !!view?.faults?.model_unavailable

  // Default to the highest-scored transfer so the score panel is never empty once scoring starts.
  const scored = (graph?.edges ?? []).filter((e: Json) => e.kind === 'transfer' && typeof e.score === 'number')
  const top = scored.reduce((b: Json, e: Json) => (!b || e.score > b.score ? e : b), null)
  const active: GraphSel = sel ?? (top ? { kind: 'edge', id: top.id } : null)

  async function toggleFault() {
    await api.post(`/v1/runs/${run.run_id}/faults`, { model_unavailable: !down })
  }

  return (
    <div className="page">
      {!compact && (
        <div className="page-head">
          <div>
            <div className="page-title"><h1>Our Engine</h1><span className="tag lg"><Icon name="gear" size={16} />Our product · Engine + API</span></div>
            <p>Connected evidence across bank, exchange and chain.</p>
          </div>
          {!present && run.mode === 'live' && (
            <button className={down ? 'primary' : 'outline'} onClick={toggleFault} style={{ display: 'inline-flex', gap: 8, alignItems: 'center', padding: '10px 18px' }}>
              <Icon name="bolt" size={17} />{down ? 'Restore model' : 'Simulate model outage'}
            </button>
          )}
        </div>
      )}
      <div className="engine-grid">
        <div className="stack" style={{ gap: 16 }}>
          {run.large && view?.network && <NetworkCard net={view.network} cases={openCases} caseId={view.cases?.[0]?.case_id}
            onCase={(id) => { setCaseId(id); setFocus(''); setSel(null) }} />}
          <div className="card">
            <div className="card-head">
              <span className="caps">Money-flow evidence graph</span>
              {graph?.focus_options?.length > 1
                ? <select value={graph.focus} onChange={(e) => { setFocus(e.target.value); setSel(null) }} aria-label="Reported account shown in the graph">
                  {graph.focus_options.map((o: Json) => <option key={o.id} value={o.id}>From {o.label} · {o.reports} report{o.reports === 1 ? '' : 's'}</option>)}
                </select>
                : <span className="sub" style={{ display: 'flex', gap: 6, alignItems: 'center' }}><Icon name="info" size={15} />Trace crosses only verified deposit links</span>}
            </div>
            {graph?.focus_options?.length > 1 && <div className="small muted" style={{ marginBottom: 8 }}>One network case, {graph.focus_options.length} reported accounts. The graph follows the money from one of them; repeated transfers between two accounts are folded into one edge.</div>}
            {graph ? <GraphView graph={graph} merchantId={run.merchant_account_id} sel={active} onSelect={setSel} /> : <div className="empty">Loading graph…</div>}
            <div className="legend">
              <span><i />Verified (confirmed record)</span>
              <span><i className="dashed" />Candidate / requested</span>
              <span><i className="dotted" />Unresolved (no record)</span>
            </div>
          </div>
          <div className="card"><Selected sel={active} graph={graph} predictions={view?.predictions ?? {}} down={down} /></div>
          {!compact && <RecLog view={view} />}
        </div>

        <div className="stack" style={{ gap: 16 }}>
          <div className="card side-card">
            <div className="card-head"><span className="caps">Model</span>
              <span className={`pill ${down ? 'bad' : 'good'}`}>● {down ? 'Unavailable' : 'Ready'}</span></div>
            {model && <>
              <div className="model-id">
                <span className="db"><Icon name="database" size={26} /></span>
                <div>
                  <b style={{ fontSize: '1.05rem' }}>{model.model_id ?? 'none'} · {model.version}</b>
                  <div className="small">{model.source?.kind === 'bundle' ? `Experiment bundle ${model.source.bundle_id}` : 'Hand-set demo rules'}</div>
                  <div className="small">Features: {model.feature_version}</div>
                </div>
              </div>
              <div className="small muted" style={{ marginTop: 10 }}>Transaction ranking score; not a probability.</div>
            </>}
          </div>

          <div className="card side-card">
            <h3><Icon name="file" size={20} />Evidence found</h3>
            {!assessment ? <div className="empty">No case opened. A case opens when a report arrives for an account.</div>
              : <ul className="check-list">{evidenceSummary(assessment.evidence).map((e) => <li key={e.label} title={e.detail}><Icon name="checkCircle" size={20} />{e.label}</li>)}</ul>}
          </div>

          <div className="card side-card benign">
            <h3><Icon name="leaf" size={20} />Benign context</h3>
            {!assessment ? <div className="empty">Appears once a case is open.</div>
              : assessment.context_benign.length === 0 ? <div className="empty">None found.</div>
                : <CappedList items={benignSummary(assessment.context_benign)} icon="checkCircle" />}
          </div>

          <div className="card side-card">
            <h3><Icon name="file" size={20} />Missing data &amp; uncertainty</h3>
            {!assessment ? <div className="empty">Appears once a case is open.</div> : (
              assessment.missing_inputs.length || assessment.uncertainty.length
                ? <CappedList warn icon="alert" items={[...assessment.missing_inputs.map(missingLabel), ...assessment.uncertainty]} />
                : <ul className="check-list"><li><Icon name="checkCircle" size={20} />None recorded for this snapshot</li></ul>
            )}
            <div className="small muted" style={{ marginTop: 12 }}>Linked evidence is not a finding of wrongdoing.</div>
          </div>
        </div>
      </div>
      {!compact && <div className="foot-note">Prototype design · Synthetic data</div>}
    </div>
  )
}

function CappedList({ items, icon, warn }: { items: string[]; icon: string; warn?: boolean }) {
  const [all, setAll] = useState(false)
  const rows = all ? items : items.slice(0, LIST_LIMIT)
  return (
    <>
      <ul className={`check-list ${warn ? 'warn' : ''}`}>{rows.map((t, i) => <li key={i}><Icon name={icon} size={20} />{t}</li>)}</ul>
      {items.length > LIST_LIMIT && <button className="ghost small" onClick={() => setAll(!all)}>{all ? 'Show fewer' : `+${items.length - LIST_LIMIT} more`}</button>}
    </>
  )
}

// Large scenarios: how big the case is and how much officer work it creates.
function NetworkCard({ net, cases, caseId, onCase }: { net: Json; cases: Json[]; caseId?: string; onCase: (id: string) => void }) {
  const stats: [string, string | number][] = [
    ['Reports', net.reports], ['Reported accounts', net.reported_accounts], ['Bank accounts traced', net.bank_accounts],
    ['Banks', net.institutions.length], ['Exchange customers', net.exchange_customers], ['Withdrawals', net.withdrawals],
    ['Awaiting officer', net.awaiting_officer], ['Held', thb(net.held_minor)],
  ]
  return (
    <div className="card">
      <div className="card-head">
        <span className="caps">Network case</span>
        {cases.length > 1 && (
          <select value={caseId} onChange={(e) => onCase(e.target.value)} aria-label="Case">
            {cases.map((c) => <option key={c.case_id} value={c.case_id}>{c.case_id} · {(c.origin_subjects?.length || 1)} reported account{(c.origin_subjects?.length || 1) > 1 ? 's' : ''}</option>)}
          </select>
        )}
      </div>
      <div className="stat-row">{stats.map(([l, v]) => <div key={l} className="stat"><span className="lbl">{l}</span><b className={l === 'Awaiting officer' && Number(v) ? 'amber' : ''}>{v}</b></div>)}</div>
      <div className="small muted" style={{ marginTop: 10 }}>Reports that reach the same accounts join one case, so each account gets one recommendation, not one per report. {net.open_cases} open case{net.open_cases === 1 ? '' : 's'} in this run.</div>
    </div>
  )
}

function evidenceSummary(ev: Json[]): { label: string; detail: string }[] {
  const by: Record<string, Json[]> = {}
  for (const e of ev) (by[e.kind] ??= []).push(e)
  const out: { label: string; detail: string }[] = []
  const join = (k: string) => by[k].map((e) => e.text).join('\n')
  if (by.external_signal) out.push({ label: by.external_signal.length > 1 ? `${by.external_signal.length} reports on source accounts` : 'Reported source account', detail: join('external_signal') })
  if (by.traced_transfer) out.push({ label: `${by.traced_transfer.length} traced transfers from the reported account`, detail: join('traced_transfer') })
  if (by.link_verified) out.push({ label: `${['One', 'Two', 'Three', 'Four'][by.link_verified.length - 1] ?? by.link_verified.length} verified deposit reference${by.link_verified.length > 1 ? 's' : ''}`, detail: join('link_verified') })
  if (by.destination_history) out.push({ label: 'Destination-wallet history', detail: join('destination_history') })
  for (const k of Object.keys(by)) if (!['external_signal', 'traced_transfer', 'link_verified', 'destination_history'].includes(k))
    out.push({ label: k.replace(/_/g, ' '), detail: join(k) })
  return out
}

function benignSummary(ctx: Json[]): string[] {
  const out: string[] = []
  for (const c of ctx) {
    const m = (c.text as string).match(/(\d+) incoming payments from (\d+) payers in (\d+) days; this amount is within its typical range/)
    if (c.kind === 'receiving_pattern' && m) { out.push(`${m[1]} receipts · ${m[2]} payers · ${m[3]} days`); out.push('Amount within usual sales range') }
    else if (c.kind === 'evidence_consistency') out.push('Receipt matches amount, time and payer')
    else out.push(c.text)
  }
  return out
}

function missingLabel(m: string): string {
  const s = m.match(/^sale_evidence_for:(.+)$/)
  return s ? `Sale evidence for ${shortId(s[1])} not yet received` : m
}

function Selected({ sel, graph, predictions, down }: { sel: GraphSel; graph: Json; predictions: Json; down: boolean }) {
  if (!graph || !sel) return <div className="empty">Select a transfer or account in the graph.</div>
  if (sel.kind === 'node') {
    const n = graph.nodes.find((x: Json) => x.id === sel.id)
    if (!n) return null
    return (
      <>
        <div className="card-head"><span className="caps">Selected account · {shortId(n.id)}</span></div>
        <dl className="kv">
          <dt>Entity</dt><dd><code>{n.id}</code></dd>
          <dt>Known since</dt><dd>{n.first_known_at}</dd>
          {n.hub && <><dt>Note</dt><dd>Exchange settlement account: a hub. The trace crosses it only by verified deposit links.</dd></>}
          {n.signals.map((s: Json, i: number) => <Fragment key={`s${i}`}><dt>Report</dt><dd>{s.category.replace(/_/g, ' ')} from {s.source}, known {hm(s.known_at)} (assertion, not adjudication)</dd></Fragment>)}
          {n.labels.map((l: Json, i: number) => <Fragment key={`l${i}`}><dt>Label</dt><dd>{l.category.replace(/_/g, ' ')} by {l.source}</dd></Fragment>)}
          <dt>In case scope</dt><dd>{n.in_case ? 'yes' : 'no'}</dd>
        </dl>
      </>
    )
  }
  const e = graph.edges.find((x: Json) => x.id === sel.id)
  if (!e) return null
  const pred = predictions[e.id]
  const score: number | null = typeof e.score === 'number' ? e.score : null
  const amount = e.asset === 'USDT' ? usdt(e.amount_minor) : thb(e.amount_minor)
  return (
    <>
      <div className="card-head"><span className="caps" style={{ textTransform: 'none' }}>Selected {e.kind === 'transfer' ? 'transfer' : e.kind.replace('_', ' ')} · {shortId(e.id)}</span></div>
      <div className="sel-grid">
        <dl className="kv">
          <dt>From</dt><dd><b>{shortId(e.source)}</b></dd>
          <dt>To</dt><dd><b>{shortId(e.target)}</b>{e.target.endsWith('9000') && <span className="muted"> (settlement hub)</span>}</dd>
          {e.amount_minor !== undefined && <><dt>Amount</dt><dd><b>{amount}</b></dd></>}
          <dt>Occurred</dt><dd>{time(e.occurred_at)} <span className="muted">· available {time(e.available_at)}</span></dd>
          {e.reference_id && <><dt>Reference</dt><dd><span className="pill teal">{e.reference_id}</span></dd></>}
          {e.method && <><dt>How linked</dt><dd>{e.method}</dd></>}
          {e.controllable_until && <><dt>Control deadline</dt><dd>{time(e.controllable_until)}</dd></>}
        </dl>
        <div className="ring">
          <ScoreRing score={score} />
          <span>{score === null ? (down ? 'model unavailable' : (e.score_status ?? 'not scored').replace(/_/g, ' ')) : `${e.model_id} ranking score`}</span>
        </div>
        <div className="reasons">
          <b>Top weighted reasons</b>
          {pred?.contributions?.length ? pred.contributions.map((c: Json, i: number) => (
            <div key={i} className="reason"><span className="w">+{Number(c.contribution).toFixed(2)}</span><span>{reasonText(c)}</span></div>
          )) : <div className="small muted" style={{ marginTop: 8 }}>{e.kind === 'transfer' ? 'No rule fired for this transfer.' : 'Only bank transfers are scored by this model.'}</div>}
        </div>
      </div>
    </>
  )
}

function reasonText(c: Json): string {
  const v = typeof c.value === 'number' ? c.value : null
  switch (c.feature) {
    case 'pass_through_ratio_24h': return 'Recent inflow sent onward'
    case 'minutes_since_src_last_inbound': return v !== null ? `Sent within ${Math.round(v)} minutes` : 'Sent soon after receiving'
    case 'src_account_age_hours': return 'Sender seen under 7 days'
    case 'src_unique_out_counterparties_1h': return 'Fan-out to 3+ counterparties'
    case 'dst_is_exchange_settlement': return 'Exchange settlement destination'
    default: return c.label ?? c.feature
  }
}

function ScoreRing({ score }: { score: number | null }) {
  const r = 52, c = 2 * Math.PI * r
  return (
    <svg width={128} height={128} viewBox="0 0 128 128" aria-label={score === null ? 'no score' : `score ${score.toFixed(2)}`}>
      <circle cx={64} cy={64} r={r} fill="none" stroke="#e2ebee" strokeWidth={10} />
      {score !== null && <circle cx={64} cy={64} r={r} fill="none" stroke="#12797d" strokeWidth={10} strokeLinecap="round"
        strokeDasharray={`${c * score} ${c}`} transform="rotate(-90 64 64)" />}
      <text x={64} y={74} textAnchor="middle" fontSize={30} fontWeight={700} fill="#0d5d63">{score === null ? '–' : score.toFixed(2)}</text>
    </svg>
  )
}

function RecLog({ view }: { view: Json }) {
  const [all, setAll] = useState(false)
  const recs: Json[] = view?.recommendations ?? []
  const main = recs.filter((r) => r.status !== 'superseded' && (r.action_type === 'RECOMMEND_RESTRICTION_REVIEW' || r.action_type === 'RECOMMEND_RELEASE_REVIEW'))
  const rows = all ? recs : main
  return (
    <div className="card">
      <div className="card-head">
        <span className="caps">Recommendation log</span>
        {recs.length > main.length && <button className="ghost small" onClick={() => setAll(!all)}>{all ? 'Show key only' : `Show all (${recs.length})`}</button>}
      </div>
      {rows.length === 0 ? <div className="empty">No recommendations yet. They appear once a report opens a case.</div> : (
        <table className="data">
          <thead><tr><th>To</th><th>Scope</th><th>Recommendation</th><th>Status</th></tr></thead>
          <tbody>
            {rows.map((r) => {
              const d = (view.decisions ?? []).filter((x: Json) => x.recommendation_id === r.recommendation_id).pop()
              const [inst, icon] = INST(r.institution)
              const scope = r.target_scope.amount_minor !== undefined
                ? r.target_scope.withdrawal_id ? `${shortId(r.target_scope.withdrawal_id)} · ${usdt(r.target_scope.amount_minor).replace('.00 ', ' ')}` : `${thb(r.target_scope.amount_minor)} hold`
                : r.target_scope.restriction_id ? `${shortId(r.target_scope.account_id)} · ${r.target_scope.restriction_id}` : shortId(r.subject_id)
              const [label, tone] = d?.outcome === 'acknowledged' ? [`${d.action.replace(/_/g, ' ').replace(/^\w/, (m: string) => m.toUpperCase())} acknowledged`, 'good'] : recStatus(r.status)
              return (
                <tr key={r.recommendation_id} style={{ opacity: r.status === 'superseded' ? 0.5 : 1 }}>
                  <td><span style={{ display: 'inline-flex', gap: 8, alignItems: 'center', fontWeight: 600 }}><Icon name={icon} size={18} />{inst}</span></td>
                  <td>{scope}</td>
                  <td><span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}><Icon name="file" size={16} />{SHORT_ACTION[r.action_type]}</span></td>
                  <td><span className={`pill ${tone}`}>{label}</span></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
