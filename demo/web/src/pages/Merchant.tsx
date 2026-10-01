import { useState } from 'react'
import { api, newKey, type Json } from '../api'
import { baht, hm, thb } from '../format'
import { Icon } from '../icons'
import { useView } from '../useRun'

type Props = { run: Json; version: number; present: boolean; compact?: boolean }

const STEPS = [
  { id: 'restricted', th: 'พักยอดเฉพาะรายการนี้' },
  { id: 'review_pending', th: 'ส่งหลักฐานแล้ว รอเจ้าหน้าที่ทบทวน' },
  { id: 'outcome', th: 'ผลการทบทวน' },
]
const STATE_TH: Record<string, string> = {
  restricted: 'พักยอดรอหลักฐาน',
  review_pending: 'รอเจ้าหน้าที่ทบทวน',
  more_info_requested: 'เจ้าหน้าที่ขอข้อมูลเพิ่ม',
  retained: 'เจ้าหน้าที่คงการพักยอด',
  released: 'ปลดการพักยอดแล้ว',
}
const NEXT_TH: Record<string, string> = {
  restricted: 'รายการรับเงินนี้เชื่อมกับการโอนที่มีรายงาน อยู่ระหว่างตรวจสอบ',
  review_pending: 'ได้รับหลักฐานแล้ว เจ้าหน้าที่ธนาคารเป็นผู้พิจารณา',
  more_info_requested: 'หลักฐานยังไม่ตรงกับรายการ กรุณาตรวจสอบและส่งใหม่',
  retained: 'เจ้าหน้าที่คงการพักยอดไว้ ติดต่อธนาคารเพื่อทราบขั้นตอนถัดไป',
  released: 'เจ้าหน้าที่ปลดการพักยอดรายการนี้แล้ว',
}
const TH_MONTH = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.']

function thDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return `${d} ${TH_MONTH[m - 1]} ${y + 543} • ${iso.slice(11, 16)}`
}

function stepIndex(state: string): number {
  if (state === 'restricted' || state === 'more_info_requested') return 0
  if (state === 'review_pending') return 1
  return 2
}

// Review flow on the right: where the account holder is in the process (English, for the audience).
function flowIndex(r: Json | undefined): number {
  if (!r) return -1
  if (r.review_state === 'restricted') return 0
  if (r.review_state === 'more_info_requested') return 1
  if (r.review_state === 'review_pending') return 2
  return 4
}

export default function Merchant({ run, version, compact }: Props) {
  const role = `merchant:${run.merchant_account_id}`
  const { data } = useView<Json>(`/v1/runs/${run.run_id}/views/${role}`, version)
  if (!data) return <div className="page empty">Loading merchant app…</div>
  const r = data.restrictions[data.restrictions.length - 1]
  const fi = flowIndex(r)
  const held = data.ledger.restricted_minor
  const flow = [
    { t: 'Restricted', d: 'Payment is held for review.', icon: 'file' },
    { t: 'Submit evidence', d: 'Account holder provides supporting documents.', icon: 'file' },
    { t: 'Officer review', d: 'Bank officer reviews evidence and network information.', icon: 'user' },
    { t: 'Release / retain / request more info', d: 'An officer makes a decision.', icon: 'check' },
  ]
  return (
    <div className="page">
      {!compact && (
        <div className="page-head">
          <div>
            <div className="page-title"><h1>Merchant</h1><span className="tag">Simulated bank app</span></div>
            <p>A clear review path for the account holder.</p>
          </div>
        </div>
      )}
      <div className="merchant-grid">
        <Phone data={data} r={r} run={run} role={role} clock={run.clock.now} />
        {!compact && (
          <div className="card" style={{ padding: 24 }}>
            <div className="caps" style={{ marginBottom: 20 }}>Review flow</div>
            {!r ? <div className="empty">No restriction on this account. Nothing for the holder to do.</div> : (
              <ul className="flow-list">
                {flow.map((s, i) => (
                  <li key={s.t} className={i < fi ? 'done' : i === fi ? 'cur' : ''}>
                    <span className="c"><Icon name={i < fi ? 'check' : s.icon} size={22} /></span>
                    <div><b>{i === 3 && fi === 4 ? `Officer decision: ${r.review_state.replace(/_/g, ' ')}` : s.t}</b><span>{s.d}</span></div>
                  </li>
                ))}
              </ul>
            )}
            <div style={{ borderTop: '1px solid var(--border)', marginTop: 4, paddingTop: 4 }}>
              {held > 0
                ? <div className="big-note amber"><Icon name="lock" size={24} />Only {thb(held)} is held</div>
                : <div className="big-note teal"><Icon name="checkCircle" size={24} />Nothing is held</div>}
              <div className="big-note teal"><Icon name="wallet" size={24} />{thb(data.ledger.available_minor)} remains usable</div>
              <div className="small" style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 16, color: 'var(--text-2)' }}>
                <Icon name="info" size={20} className="teal" />Balances change after an officer decision.</div>
            </div>
          </div>
        )}
      </div>
      {!compact && <div className="foot-note">Prototype design · Synthetic data</div>}
    </div>
  )
}

function Phone({ data, r, run, role, clock }: { data: Json; r: Json | undefined; run: Json; role: string; clock: string }) {
  return (
    <div className="phone">
      <div className="phone-notch" />
      <div className="phone-status"><span>{hm(clock)}</span><span style={{ letterSpacing: 2 }}>▮▮▮ ◔</span></div>
      <div className="phone-bar"><b>แอปธนาคาร B (จำลอง)</b><div>Synthetic</div></div>
      <div className="phone-body">
        <div className="acct">
          <span className="av"><Icon name="store" size={22} /></span>
          <div><b>{data.holder_name.replace(' (synthetic)', '')}</b><div className="small muted">บัญชี •{data.display.split('•').pop()}</div></div>
        </div>
        <div className="bal">
          <div className="top"><div className="small muted">ยอดเงินทั้งหมด</div><b>{baht(data.ledger.total_minor)}</b></div>
          <div className="split">
            <div className="use"><div className="small">ใช้ได้</div><b>{baht(data.ledger.available_minor)}</b></div>
            <div className="hold"><div className="small">ถูกพักไว้</div><b>{baht(data.ledger.restricted_minor)}</b></div>
          </div>
        </div>
        {r ? <RestrictionCard r={r} run={run} role={role} fixtures={data.fixtures} /> : <>
          <div className="ok-strip"><Icon name="checkCircle" size={18} />ไม่มีรายการที่ถูกพักยอด</div>
          <div className="small muted" style={{ marginTop: 4 }}>รายการรับเงินวันนี้</div>
          {data.incoming.length === 0 ? <div className="empty">ยังไม่มีรายการ</div> : [...data.incoming].reverse().map((t: Json) => (
            <div key={t.event_id} className="row small" style={{ borderBottom: '1px solid var(--border)', padding: '6px 0' }}>
              <span>{t.payment_format === 'qr' ? 'รับเงินผ่าน QR' : 'รับโอน'} จาก {t.payer_hint}</span>
              <span><b>+{baht(t.amount_minor)}</b> <span className="muted">{hm(t.occurred_at)}</span></span>
            </div>
          ))}
        </>}
      </div>
    </div>
  )
}

function RestrictionCard({ r, run, role, fixtures }: { r: Json; run: Json; role: string; fixtures: Json[] }) {
  const [fixture, setFixture] = useState(fixtures[0]?.fixture_ref ?? '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const idx = stepIndex(r.review_state)
  const released = r.review_state === 'released'
  const canSubmit = run.mode !== 'recorded' && r.status === 'active' && ['restricted', 'more_info_requested'].includes(r.review_state)

  async function submit() {
    setBusy(true); setErr(null)
    try {
      await api.post(`/v1/runs/${run.run_id}/cases/${r.case_id}/evidence`,
        { restriction_id: r.restriction_id, fixture_ref: fixture, idempotency_key: newKey() }, { 'X-Sim-Role': role })
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  const tx = r.related_transaction
  return (
    <>
      <div className={`hold-card ${released ? 'ok' : ''}`}>
        <div className="hd">
          <span className="ic"><Icon name={released ? 'check' : 'file'} size={22} /></span>
          <div>
            <b className={released ? 'good' : 'amber'}>{STATE_TH[r.review_state] ?? r.review_state}</b>
            <div className="amt">{baht(r.amount_minor)}</div>
            {tx && <div className="small">{tx.payment_format === 'qr' ? 'รับเงินผ่าน QR' : 'รับโอน'} จาก {tx.payer_hint}</div>}
            {tx && <div className="small muted">{thDate(tx.occurred_at.replace(' ', 'T'))}</div>}
          </div>
        </div>
        <div className="small" style={{ borderTop: '1px solid var(--amber-line)', marginTop: 10, paddingTop: 8 }}>{NEXT_TH[r.review_state]}</div>
      </div>
      <ul className="p-steps">
        {STEPS.map((s, i) => (
          <li key={s.id} className={i < idx || released ? 'done' : i === idx ? 'cur' : ''}>
            {i === 2 && idx === 2 ? `ผลการทบทวน: ${STATE_TH[r.review_state]}` : s.th}
          </li>
        ))}
      </ul>
      {canSubmit && (
        <div className="ev-box">
          <b>หลักฐานการขาย</b>
          <select value={fixture} onChange={(e) => setFixture(e.target.value)} aria-label="Evidence document">
            {fixtures.map((f) => <option key={f.fixture_ref} value={f.fixture_ref}>{f.title}</option>)}
          </select>
          <button className="primary" disabled={busy || !fixture} onClick={submit}>ส่งหลักฐาน</button>
          <div className="xs muted" style={{ textAlign: 'center', marginTop: 6 }}>การส่งหลักฐานไม่ได้ปลดยอดอัตโนมัติ<br />ผู้รับผิดชอบ: ทีมทบทวนธนาคาร B</div>
          {err && <div className="callout bad"><Icon name="alert" size={16} />{err}</div>}
        </div>
      )}
      {r.submissions.length > 0 && !canSubmit && (
        <div className="ev-box small">ส่งหลักฐานแล้ว {r.submissions.length} ครั้ง (ล่าสุด {hm(r.submissions[r.submissions.length - 1].submitted_at.replace(' ', 'T'))})</div>
      )}
      <div className="ok-strip"><Icon name="info" size={18} />ยอดส่วนอื่นยังใช้ได้ตามปกติ</div>
    </>
  )
}
