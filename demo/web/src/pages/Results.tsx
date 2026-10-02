import { useEffect, useState } from 'react'
import { api, apiUrl, type Json } from '../api'
import { Icon } from '../icons'
import { t } from '../i18n'

type Props = { run: Json; version: number; present: boolean }

// Every number on this page is read from an experiment result bundle. Nothing is typed in.
export default function Results({ present }: Props) {
  const dev = new URLSearchParams(window.location.search).get('dev') === '1'
  const [list, setList] = useState<Json | null>(null)
  const [bid, setBid] = useState<string | null>(null)
  const [bundle, setBundle] = useState<Json | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [lat, setLat] = useState<Json | null>(null)

  useEffect(() => {
    api.get(`/v1/experiments${dev ? '?include_dev=true' : ''}`).then((l) => {
      setList(l)
      if (l.bundles.length) setBid(l.bundles[0].id)
    }).catch((e) => setErr(e.message))
    api.get('/v1/metrics/latency').then(setLat).catch(() => {})
  }, [dev])
  useEffect(() => {
    if (!bid) return
    api.get(`/v1/experiments/${bid}/results${dev ? '?include_dev=true' : ''}`).then(setBundle).catch((e) => setErr(e.message))
  }, [bid, dev])

  const m = bundle?.manifest
  const results: Json[] = bundle?.results ?? []
  const pos = results.find((r) => r.positive_count !== undefined)
  const limitations: string[] = m?.limitations ?? []
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="page-title"><h1>{t('Experiment Results')}</h1></div>
          {!present && <p>{t('Frozen experiment runs, separate from the demo story.')}</p>}
        </div>
        {list?.bundles?.length > 1 && (
          <select value={bid ?? ''} onChange={(e) => setBid(e.target.value)} aria-label={t('Result bundle')}>
            {list.bundles.map((b: Json) => <option key={b.id} value={b.id}>{b.id} ({b.status})</option>)}
          </select>
        )}
      </div>
      {err && <div className="callout bad" style={{ marginBottom: 16 }}><Icon name="alert" size={16} />{err}</div>}
      {bundle && !bundle.presentable && (
        <div className="callout bad" style={{ marginBottom: 16 }}><Icon name="alert" size={16} /><b>{t('DEV FIXTURE: NOT A RESULT.')}</b> {t('Shown only because ?dev=1 is set.')}</div>
      )}
      {list && !bundle && (
        <div className="banner">
          <span className="ic"><Icon name="alert" size={26} /></span>
          <div>
            <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}><b>{t('No completed experiment bundle yet')}</b><span className="pill amber">not_run</span></div>
            <div style={{ marginTop: 4 }}>{t('Results appear after a completed bundle is imported. Unrun metrics are unavailable, not zero.')}</div>
          </div>
        </div>
      )}

      <div className="grid" style={{ gap: 16 }}>
        <div className="results-top">
          <RecallChart results={results} />
          <div className="card">
            <div className="card-head"><span className="caps">{t('Run provenance')}</span>{m && <span className={`pill ${m.status === 'completed' ? 'good' : 'amber'}`}>{m.status}</span>}</div>
            <dl className="kv right">
              <dt>{t('Run ID')}</dt><dd>{m ? <code>{m.run_id}</code> : '–'}</dd>
              <dt>{t('Dataset / version')}</dt><dd>{m ? `${m.dataset?.id ?? ''} ${m.dataset?.version ?? ''}` : '–'}</dd>
              <dt>{t('Split')}</dt><dd>{m?.split ? (typeof m.split === 'string' ? m.split : JSON.stringify(m.split)) : '–'}</dd>
              <dt>{t('Eligible / positives')}</dt><dd>{pos ? `${pos.eligible_count ?? '-'} / ${pos.positive_count}` : '–'}</dd>
              <dt>{t('Parity')}</dt><dd>{bundle?.parity ? `${bundle.parity.status} (${bundle.parity.arm})` : '–'}</dd>
            </dl>
            <div className="small muted" style={{ borderTop: '1px solid var(--border)', marginTop: 14, paddingTop: 10 }}>{t('Populated from the experiment bundle.')}</div>
            {bundle?.failures?.length > 0 && <>
              <div className="section-label">{t('Failed or deferred')}</div>
              <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{bundle.failures.map((f: Json, i: number) => <li key={i}>{typeof f === 'string' ? f : JSON.stringify(f)}</li>)}</ul>
            </>}
          </div>
        </div>

        {bundle ? <MetricsTable results={results} /> : <StatusTable arms={list?.template_arms ?? []} />}
        {bundle?.comparisons?.length > 0 && <Comparisons rows={bundle.comparisons} />}
        {bundle?.figures?.length > 0 && !present && (
          <div className="card"><div className="card-head"><span className="caps">{t('Exported figures')}</span></div>
            <div className="grid cols-2">{bundle.figures.map((f: string) => <img key={f} alt={f} style={{ maxWidth: '100%' }} src={apiUrl(`/v1/experiments/${bundle.id}/figures/${f}`)} />)}</div></div>
        )}

        <div className="results-bottom">
          <div className="card">
            <div className="card-head"><span className="card-title"><span className="caps">{t('Engine API latency')}</span><span className="tag">{t('Separate from benchmark')}</span></span></div>
            <div className="lat">
              <div><span className="muted">p50</span><b>{lat?.n ? `${lat.p50_ms} ms` : '–'}</b></div>
              <div><span className="muted">p95</span><b>{lat?.n ? `${lat.p95_ms} ms` : '–'}</b></div>
            </div>
            <div className="small muted" style={{ marginTop: 10 }}>{lat?.n ? t('Over {n} assessments in this demo session; {scope}.', { n: lat.n, scope: lat.scope }) : t('Live measurements populate during a running session.')}</div>
          </div>
          <div className="card">
            <div className="card-head"><span className="caps">{t('Limitations')}</span></div>
            <ul className="lim">
              <li><Icon name="database" size={20} />{t('Synthetic demo; no live bank or chain connection')}</li>
              <li><Icon name="gear" size={20} />{t('R0-demo uses hand-set rules')}</li>
              {!bundle && <li><Icon name="file" size={20} />{t('No completed benchmark results loaded')}</li>}
              {limitations.map((x, i) => <li key={i}><Icon name="file" size={20} />{x}</li>)}
            </ul>
            <div className="small muted" style={{ borderTop: '1px solid var(--border)', marginTop: 14, paddingTop: 10 }}>{t('Development fixtures are excluded from reported results.')}</div>
          </div>
        </div>
      </div>
      <div className="foot-note">{t('Prototype design · Synthetic data')}</div>
    </div>
  )
}

function StatusTable({ arms }: { arms: Json[] }) {
  const v = (x: string) => (x === '' || x === undefined ? '–' : x)
  return (
    <div className="card">
      <div className="card-head"><span className="caps">{t('Experiment status')}</span></div>
      <table className="data">
        <thead><tr><th>{t('Suite')}</th><th>{t('Arm')}</th><th>{t('Status')}</th><th className="r">{t('Recall')}</th><th className="r">{t('Precision')}</th><th className="r">{t('False alerts')}</th></tr></thead>
        <tbody>{arms.map((a: Json, i: number) => (
          <tr key={i} title={a.notes}><td><b>{a.suite}</b></td><td>{a.arm}</td><td><span className={`pill ${a.status === 'completed' ? 'good' : 'amber'}`}>{a.status}</span></td>
            <td className="r">{v(a.recall_at_k)}</td><td className="r">{v(a.precision_at_k)}</td><td className="r">{v(a.false_alert_count)}</td></tr>
        ))}</tbody>
      </table>
    </div>
  )
}

const ARM_ORDER = ['R0', 'L0', 'L1', 'G1', 'A0', 'G2']
function ordered(results: Json[]): Json[] {
  const rank = (a: string) => { const i = ARM_ORDER.indexOf(a); return i < 0 ? 99 : i }
  return [...results].sort((a, b) => rank(a.arm) - rank(b.arm) || String(a.arm).localeCompare(String(b.arm)))
}

function pct(x: number | null | undefined) { return x === null || x === undefined ? '-' : `${(x * 100).toFixed(1)}%` }

function RecallChart({ results }: { results: Json[] }) {
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null)
  const budget = results.find((r) => r.review_budget_fraction)?.review_budget_fraction
  return (
    <div className="card">
      <div className="card-head"><span className="caps">{t('Recall at {b} review budget', { b: budget ? `${budget * 100}%` : '1%' })}</span>
        <span className="arm-tabs">{['R0', 'L0', 'L1', 'G1', 'G2 when completed'].map((a) => <span key={a}>{t(a)}</span>)}</span></div>
      {results.length === 0 && (
        <div className="empty-state">
          <span className="bubble"><Icon name="chart" size={40} /></span>
          <b>{t('Awaiting completed results')}</b>
          <span className="small">{t('Results will be shown for R0, L0, L1, G1 and G2 when a completed bundle is imported.')}</span>
        </div>
      )}
      <div className="bars">
        {ordered(results).map((r) => {
          const v = r.metrics?.recall_at_budget
          const done = r.status === 'completed' && v !== null && v !== undefined
          return (
            <div key={r._file} className="bar-row"
              onMouseMove={(e) => done && setTip({ x: e.clientX + 12, y: e.clientY + 12, text: `${r.arm}: recall ${pct(v)}, precision ${pct(r.metrics?.precision_at_budget)}, false alerts ${r.metrics?.false_alert_count ?? '-'}, n=${r.eligible_count ?? '-'}` })}
              onMouseLeave={() => setTip(null)}>
              <span>{r.arm}</span>
              <div className="bar-track">{done ? <div className="bar-fill" style={{ width: `${Math.max(1, v * 100)}%` }} /> : <span className="notrun">{t('not completed ({s})', { s: r.status })}</span>}</div>
              <span className="mono">{done ? pct(v) : ''}</span>
            </div>
          )
        })}
      </div>
      {tip && <div className="tooltip" style={{ left: tip.x, top: tip.y }}>{tip.text}</div>}
    </div>
  )
}

function MetricsTable({ results }: { results: Json[] }) {
  return (
    <div className="card">
      <div className="card-head"><span className="caps">{t('Metrics by arm')}</span><span className="sub">{t('table view of the chart, plus resources')}</span></div>
      <table className="data">
        <thead><tr><th>{t('Arm')}</th><th>{t('Status')}</th><th>{t('Eligible')}</th><th>{t('Positives')}</th><th>{t('Recall')}</th><th>{t('Precision')}</th><th>{t('False alerts')}</th><th>AP</th><th>{t('Train s')}</th><th>{t('p95 inference ms')}</th></tr></thead>
        <tbody>{ordered(results).map((r) => (
          <tr key={r._file}>
            <td>{r.arm}</td><td>{r.status}</td>
            <td className="r">{r.eligible_count ?? '-'}</td><td className="r">{r.positive_count ?? '-'}</td>
            <td className="r">{pct(r.metrics?.recall_at_budget)}</td><td className="r">{pct(r.metrics?.precision_at_budget)}</td>
            <td className="r">{r.metrics?.false_alert_count ?? '-'}</td><td className="r">{r.metrics?.average_precision?.toFixed?.(3) ?? '-'}</td>
            <td className="r">{r.resource_usage?.train_seconds ?? '-'}</td><td className="r">{r.resource_usage?.inference_p95_ms ?? '-'}</td>
          </tr>))}
        </tbody>
      </table>
    </div>
  )
}

function Comparisons({ rows }: { rows: Json[] }) {
  const cols = Object.keys(rows[0])
  return (
    <div className="card">
      <div className="card-head"><span className="caps">{t('Paired comparisons')}</span><span className="sub">{t('same cohort and budget; percentage points')}</span></div>
      <table className="data"><thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{cols.map((c) => <td key={c}>{r[c]}</td>)}</tr>)}</tbody></table>
    </div>
  )
}
