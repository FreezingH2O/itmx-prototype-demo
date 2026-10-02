import type { Json } from '../api'
import { t } from '../i18n'

const percent = (n: number) => `${(n * 100).toFixed(2)}%`
const ARM_ORDER = ['R0', 'L0', 'L1', 'G1', 'A0', 'G2']
const byArm = (a: Json, b: Json) => ARM_ORDER.indexOf(a.arm) - ARM_ORDER.indexOf(b.arm)

export function DataScope({ design }: { design: Json }) {
  const sim = design.simulation_scope
  const train = design.training_setup
  return <div className="card">
    <div className="card-head"><span className="caps">{t('Dataset scope and allocation')}</span></div>
    <p>{t('IBM data and the team-created 500,000 events are separate datasets. Publisher counts below follow the Kaggle dataset page (v8) and are approximate; test sizes are estimates that use a rounded 20% split of those totals.')}</p>
    <div className="table-scroll"><table className="data">
      <thead><tr><th>{t('Dataset / version')}</th><th>{t('Publisher transactions (approx.)')}</th><th>{t('Publisher accounts (approx.)')}</th><th>{t('Laundering transactions (approx.)')}</th><th>{t('Publisher laundering rate')}</th><th>{t('Test rows / positives')}</th></tr></thead>
      <tbody>{design.dataset_scope.map((r: Json) => <tr key={r.key}><td>{r.file} · v{r.version_proposed}</td><td>≈ {r.publisher_transactions_approx.toLocaleString()}</td><td>≈ {r.publisher_accounts_approx.toLocaleString()}</td><td>≈ {r.publisher_laundering_transactions_approx.toLocaleString()}</td><td>1 / {r.publisher_laundering_rate_one_per_transactions.toLocaleString()}</td><td>≈ {r.test_rows.toLocaleString()} / ≈ {r.test_positives.toLocaleString()}</td></tr>)}</tbody>
    </table></div>
    <p className="small muted">{t('Test counts use the publisher prevalence rate. Its small-dataset counts are rounded, so the count and rate do not divide to an exact match. Whole-timestamp splitting, the history warm-up and the excluded tail can change test counts.')}</p>
    <div className="callout">{t('Laundering is very rare in these datasets (about 1 in 1,000 transactions or fewer), so this page does not report accuracy. Models are compared by how much laundering they catch within a fixed review workload; the reason is explained in the next card.')}</div>
    <p className="small muted">{t('IBM primary window: 1–10 September 2022; the later tail is excluded from headline results. Temporal split 60/20/20; the first 24 hours are history warm-up.')}</p>
    <b>{t('Team simulation: 500,000 events')}</b>
    <p>{t('5 worlds × 100,000 events = 500,000 events total; each world spans 30 simulated days. Allocation: 300,000 train / 100,000 validation / 100,000 test.')}</p>
    <div className="table-scroll"><table className="data">
      <thead><tr><th>{t('Event type')}</th><th>{t('Total')}</th><th>{t('Train')}</th><th>{t('Validation')}</th><th>{t('Test')}</th></tr></thead>
      <tbody>{sim.allocation.map((r: Json) => <tr key={r.event_type}><td>{t(r.event_type)}</td><td>{r.nominal_total.toLocaleString()}</td><td>{r.nominal_train.toLocaleString()}</td><td>{r.nominal_validation.toLocaleString()}</td><td>{r.nominal_test.toLocaleString()}</td></tr>)}</tbody>
    </table></div>
    <p className="small muted">{t('Event-type proportions are design assumptions, not measured counts. The 500,000-event target and the 60/20/20 split come from the protocol.')}</p>
    <p className="small muted">{t('Model seeds: {seeds}. World seeds: {worlds}. LightGBM: up to {lgb} configurations, {rounds} rounds, patience {pl}. GNN: up to {gnn} configurations, {epochs} epochs, patience {pg}.', { seeds: train.seeds.join(', '), worlds: sim.planned_world_seeds.join(', '), lgb: train.lightgbm_max_configs_per_arm, rounds: train.lightgbm_max_rounds, pl: train.lightgbm_early_stopping, gnn: train.gnn_max_configs, epochs: train.gnn_initial_profile.max_epochs, pg: train.gnn_initial_profile.early_stopping })}</p>
    <p className="small muted">{t('GNN profile: {layers} layers, hidden size {hidden}, fanout {fanout}, batch size {batch}. IBM validation is split in half for tuning and threshold selection.', { layers: train.gnn_initial_profile.layers, hidden: train.gnn_initial_profile.hidden, fanout: train.gnn_initial_profile.fanout.join('/'), batch: train.gnn_initial_profile.batch_size })}</p>
  </div>
}

export function MetricRationale({ design, results, dataset }: { design: Json; results: Json[]; dataset: Json }) {
  const budget: number = design.metric_setup.review_fraction
  const reviews = Math.round(dataset.test_rows * budget)
  const eg = results.find((r) => r.arm === 'G1')
  const b = `${budget * 100}%`
  const budgets: number[] = [...design.metric_setup.sensitivity_fractions, budget].sort((x, y) => x - y)
  const recallAt = (r: Json, f: number) => r.sensitivity?.find((s: Json) => s.review_budget_fraction === f)?.recall
  return <div className="card">
    <div className="card-head"><span className="caps">{t('Why we compare models at a {b} review budget', { b })}</span></div>
    <p>{t('Laundering is rare here: about {pos} of {rows} test transactions ({rate}). A model that calls everything normal would still score {acc} accuracy while catching nothing, so accuracy is not used.', { pos: dataset.test_positives.toLocaleString(), rows: dataset.test_rows.toLocaleString(), rate: `${(dataset.assumed_prevalence * 100).toFixed(2)}%`, acc: `${((1 - dataset.assumed_prevalence) * 100).toFixed(2)}%` })}</p>
    <p>{t('Reviewers can only check a small share of transactions. So every model gets the same workload: it ranks all test transactions by risk and may send only the top {b} ({n} transactions) to review. Recall is the share of the real laundering cases that land inside that list.', { b, n: reviews.toLocaleString() })}</p>
    <p>{t('One fixed workload keeps the comparison fair: differences between models come from how well they rank risk, not from one model raising more alerts than another.')}</p>
    {eg && <div className="callout">{t('Example, {arm}: of {n} reviewed transactions, {tp} are real laundering, so recall = {tp} / {pos} = {r}. The other {fn} laundering cases are missed, and the remaining {fp} reviews are false alerts.', { arm: eg.arm, n: reviews.toLocaleString(), tp: eg.confusion_counts.tp.toLocaleString(), pos: dataset.test_positives.toLocaleString(), r: percent(eg.metrics.recall_at_budget), fn: eg.confusion_counts.fn.toLocaleString(), fp: eg.confusion_counts.fp.toLocaleString() })}</div>}
    <div className="section-label">{t('Recall at other review budgets')}</div>
    <div className="table-scroll"><table className="data">
      <thead><tr><th>{t('Arm')}</th>{budgets.map((f) => <th key={f} className="r">{`${f * 100}%`}</th>)}</tr></thead>
      <tbody>{[...results].sort(byArm).map((r) => <tr key={r.arm}><td>{r.arm}</td>{budgets.map((f) => <td key={f} className="r">{recallAt(r, f) === undefined ? '–' : percent(recallAt(r, f))}</td>)}</tr>)}</tbody>
    </table></div>
    <p className="small muted">{t('{b} is a working point chosen by the team, not an industry standard. It means about {k} reviews for every real case, so precision cannot exceed about {cap} at this budget. The table above shows how recall changes when review capacity changes.', { b, k: (reviews / dataset.test_positives).toFixed(0), cap: `${(dataset.test_positives / reviews * 100).toFixed(1)}%` })}</p>
    <p className="small muted">{t('This is a ranking comparison on past data. The alert threshold for a pilot is chosen separately on validation data (targets: recall at least 80%, at most 5% of transactions reviewed) and is never tuned on test data. No threshold-feasibility or non-inferiority result is reported.')}</p>
  </div>
}

function SampleRecords({ sample }: { sample: Json }) {
  const cols = Object.keys(sample.records[0])
  return <div className="card">
    <div className="card-head"><span className="caps">{t('Synthetic event sample')}</span></div>
    <p className="small muted">{t('A small sample of synthetic event records. The full synthetic linkage data is not shared.')}</p>
    <div className="table-scroll"><table className="data"><thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>{sample.records.map((r: Json, i: number) => <tr key={i}>{cols.map((c) => <td key={c}>{String(r[c] ?? '–')}</td>)}</tr>)}</tbody></table></div>
  </div>
}

export default function Experiments({ results, sample }: { results: Json[]; sample: Json | null }) {
  const g1 = results.find((r) => r.arm === 'G1')
  const g2 = results.find((r) => r.arm === 'G2')
  return <>
    {g1 && g2 && <div className="card">
      <div className="card-head"><span className="caps">{t('Model comparison')}</span></div>
      <div className="choice"><b>G1 · LightGBM + graph features</b>
        <p>{t('At the same 1% review budget, recall is {g1} for G1 and {g2} for G2, a smaller GINE-style GNN rather than IBM Multi-PNA+EU. IBM reports minority-class F1, a different metric, so published numbers guide which arms we test but are not compared directly with these.', { g1: percent(g1.metrics.recall_at_budget), g2: percent(g2.metrics.recall_at_budget) })}</p>
      </div>
    </div>}
    {sample?.records?.length > 0 && <SampleRecords sample={sample} />}
  </>
}
