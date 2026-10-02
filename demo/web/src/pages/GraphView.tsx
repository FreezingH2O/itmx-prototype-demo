import type { Json } from '../api'
import { shortId, thb, usdt } from '../format'
import { t } from '../i18n'
import type { Path } from '../graphPath'

// Lane graph: Bank | Exchange | Chain, laid out left to right in money-flow order.
// The exchange settlement account is a hub: it is not drawn as a node. A transfer into it is drawn
// as a deposit-reference box, and the trace crosses into the exchange only through deposit links.

export type GraphSel = { kind: 'edge' | 'node'; id: string } | null
type Pt = { x: number; y: number }
type N = Pt & { id: string; raw: Json; col: number; role: string }

const MAX_DEPTH = 8   // transfers can form loops; cap the column count so the graph cannot run away
const COL_W = 132
const ROW_H = 96
const TOP = 74
const PAD_X = 52

const C = {
  teal: '#12797d', tealDark: '#0d5d63', tealSoft: '#e2f2f1', line: '#2c8a8e', gray: '#7b8a93', amber: '#b4630f',
  amberSoft: '#fcf0dd', path: '#d9480f', text: '#0c1f2b', text2: '#475965', laneBank: '#eef5f7', laneEx: '#e9f3f4', laneChain: '#e4f0f1',
}

function bankLabel(id: string) { return shortId(id) }

export default function GraphView({ graph, merchantId, sel, path, onSelect }: { graph: Json; merchantId?: string; sel: GraphSel; path?: Path | null; onSelect: (s: GraphSel) => void }) {
  // With a selected path, everything off the path fades.
  const fade = (on: boolean) => (path && !on ? 0.15 : 1)
  const onE = (id: string) => !!path?.edges.has(id)
  const onN = (id: string) => !!path?.nodes.has(id)
  const hubs = new Set(graph.nodes.filter((n: Json) => n.hub).map((n: Json) => n.id))
  const flagged = (n: Json) => (n.signals?.length ?? 0) > 0 || (n.labels?.length ?? 0) > 0
  const isChainVisible = (n: Json) => n.in_case || n.labels.length > 0
  const visible = graph.nodes.filter((n: Json) => !n.hub && (n.lane !== 'chain' || isChainVisible(n)))
  const vis = new Set(visible.map((n: Json) => n.id))

  const transfers = graph.edges.filter((e: Json) => e.kind === 'transfer').sort((a: Json, b: Json) => a.occurred_at.localeCompare(b.occurred_at))
  const bankEdges = transfers.filter((e: Json) => vis.has(e.source) && vis.has(e.target))
  const hubEdges = transfers.filter((e: Json) => vis.has(e.source) && hubs.has(e.target))
  const depLinks = graph.edges.filter((e: Json) => e.kind === 'deposit_link')
  const withdrawals = graph.edges.filter((e: Json) => e.kind === 'withdrawal')
  const chainEdges = graph.edges.filter((e: Json) => e.kind === 'chain' && vis.has(e.source) && vis.has(e.target))

  // --- columns
  const depth: Record<string, number> = {}
  const bankNodes = visible.filter((n: Json) => n.lane.startsWith('bank'))
  for (const n of bankNodes) depth[n.id] = 0
  for (let i = 0; i < bankNodes.length; i++) for (const e of bankEdges) depth[e.target] = Math.min(MAX_DEPTH, Math.max(depth[e.target] ?? 0, (depth[e.source] ?? 0) + 1))
  const maxBank = Math.max(0, ...Object.values(depth))
  const docCol = maxBank + 1
  const exCol = docCol + (hubEdges.length ? 1 : 0)
  const wdCol = exCol + 1
  const chainCol = wdCol + 1

  // --- rows: leaves of the bank lane in transfer order, parents centred over children
  const y: Record<string, number> = {}
  let next = 0
  const leafOrder: string[] = []
  for (const e of bankEdges) if (depth[e.target] === maxBank && !leafOrder.includes(e.target)) leafOrder.push(e.target)
  for (const n of bankNodes) if (depth[n.id] === maxBank && !leafOrder.includes(n.id)) leafOrder.push(n.id)
  for (const id of leafOrder) y[id] = next++
  for (let d = maxBank - 1; d >= 0; d--) {
    for (const n of bankNodes.filter((m: Json) => depth[m.id] === d)) {
      const kids = bankEdges.filter((e: Json) => e.source === n.id && y[e.target] !== undefined).map((e: Json) => y[e.target])
      y[n.id] = kids.length ? kids.reduce((a: number, b: number) => a + b, 0) / kids.length : next++
    }
  }
  const exNodes = visible.filter((n: Json) => n.lane === 'exchange')
  for (const n of exNodes) {
    const l = depLinks.find((e: Json) => e.target === n.id && y[e.source] !== undefined)
    y[n.id] = l ? y[l.source] : next++
  }
  const wdNodes: N[] = []
  const pos: Record<string, N> = {}
  const X = (col: number) => PAD_X + col * COL_W + COL_W / 2
  const Y = (row: number) => TOP + row * ROW_H
  for (const n of [...bankNodes, ...exNodes]) {
    pos[n.id] = { id: n.id, raw: n, col: n.lane === 'exchange' ? exCol : depth[n.id], role: n.lane === 'exchange' ? 'customer' : 'bank', x: X(n.lane === 'exchange' ? exCol : depth[n.id]), y: Y(y[n.id] ?? 0) }
  }
  for (const w of withdrawals) {
    const from = pos[w.source]
    const row = from ? (from.y - TOP) / ROW_H : next++
    const id = `wd:${w.id}`
    const node: N = { id, raw: w, col: wdCol, role: 'withdrawal', x: X(wdCol), y: Y(row) }
    pos[id] = node; wdNodes.push(node)
  }
  // chain: destination beside its withdrawal, other chain nodes stacked below it
  const chainNodes = visible.filter((n: Json) => n.lane === 'chain')
  const dests = new Set(withdrawals.map((w: Json) => w.target))
  let chainRow = wdNodes.length ? (wdNodes[0].y - TOP) / ROW_H : 0
  for (const n of [...chainNodes].sort((a: Json, b: Json) => Number(dests.has(b.id)) - Number(dests.has(a.id)))) {
    const w = wdNodes.find((m) => m.raw.target === n.id)
    const row = w ? (w.y - TOP) / ROW_H : chainRow + 1.6
    chainRow = row
    pos[n.id] = { id: n.id, raw: n, col: chainCol, role: dests.has(n.id) ? 'destination' : 'chain', x: X(chainCol), y: Y(row) }
  }

  const rows = Math.max(1, ...Object.values(pos).map((p) => (p.y - TOP) / ROW_H + 1))
  const W = PAD_X * 2 + (chainCol + 1) * COL_W
  const H = TOP + (rows - 1) * ROW_H + 92
  const laneX = (col: number) => PAD_X + col * COL_W
  const exStart = laneX(exCol)
  const chainStart = laneX(chainCol)

  const isSel = (kind: 'edge' | 'node', id: string) => sel?.kind === kind && sel.id === id
  const edgeColor = (e: Json) => (e.in_case ? C.line : C.gray)

  return (
    <svg className="svg-graph" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Money-flow evidence graph">
      <defs>
        {['t', 'g'].map((k) => (
          <marker key={k} id={`arr-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0L10 5L0 10z" fill={k === 't' ? C.line : C.gray} />
          </marker>
        ))}
      </defs>
      {/* lanes */}
      <rect x={8} y={8} width={exStart - 12} height={H - 16} rx={12} fill={C.laneBank} />
      <rect x={exStart} y={8} width={chainStart - exStart - 4} height={H - 16} rx={12} fill={C.laneEx} />
      <rect x={chainStart} y={8} width={W - chainStart - 8} height={H - 16} rx={12} fill={C.laneChain} />
      <LaneTitle x={(8 + exStart) / 2} label={t('Bank')} icon="bank" />
      <LaneTitle x={(exStart + chainStart) / 2} label={t('Exchange')} icon="swap" />
      <LaneTitle x={(chainStart + W) / 2} label={t('Chain')} icon="cube" />

      {/* bank transfers */}
      {bankEdges.map((e: Json) => {
        const a = pos[e.source], b = pos[e.target]
        if (!a || !b) return null
        return (
          <g key={e.id} className="node" opacity={fade(onE(e.id))} onClick={() => onSelect({ kind: 'edge', id: e.id })}>
            <Edge a={a} b={b} color={onE(e.id) ? C.path : edgeColor(e)} width={isSel('edge', e.id) ? 4 : onE(e.id) ? 3 : 2} />
            <EdgeLabel a={a} b={b} text={e.count > 1 ? `${e.count}× ${thb(e.amount_minor)}` : thb(e.amount_minor)} />
          </g>
        )
      })}
      {/* transfers into the settlement hub, drawn as deposit-reference boxes */}
      {hubEdges.map((e: Json) => {
        const a = pos[e.source]
        if (!a) return null
        const bx = X(docCol), by = a.y
        const link = depLinks.find((l: Json) => l.source === e.source)
        const cust = link ? pos[link.target] : null
        const dash = link?.status === 'candidate' ? '7 5' : link?.status === 'unresolved' ? '2 5' : undefined
        return (
          <g key={e.id} className="node" opacity={fade(onE(e.id) || (!!link && onE(link.id)))} onClick={() => onSelect({ kind: 'edge', id: e.id })}>
            <Edge a={a} b={{ x: bx - 37, y: by }} color={edgeColor(e)} width={isSel('edge', e.id) ? 4 : 2} />
            <rect x={bx - 62} y={by - 25} width={124} height={50} rx={8} fill="#fff" stroke={isSel('edge', e.id) ? C.teal : '#c6d4d8'} strokeWidth={isSel('edge', e.id) ? 2.5 : 1.2} />
            <text x={bx} y={by - 7} textAnchor="middle" fontSize={11} fill={C.text2}>{t('To')} {shortId(e.target)} · {thb(e.amount_minor)}</text>
            {e.reference_id
              ? <><rect x={bx - 36} y={by + 1} width={72} height={18} rx={4} fill={C.tealSoft} /><text x={bx} y={by + 14} textAnchor="middle" fontSize={11} fontWeight={700} fill={C.tealDark}>{e.reference_id}</text></>
              : <text x={bx} y={by + 14} textAnchor="middle" fontSize={11} fill={C.amber}>{t('no reference')}</text>}
            {cust && <>
              <Edge a={{ x: bx + 38, y: by }} b={cust} color={link.status === 'verified' ? C.line : C.gray} width={link.status === 'verified' ? 2.5 : 1.6} dash={dash} />
              <text x={(bx + 62 + cust.x - 24) / 2} y={by - 8} textAnchor="middle" fontSize={11} fontWeight={700} fill={link.status === 'verified' ? C.tealDark : C.gray}>
                {t(link.status === 'verified' ? 'Verified' : link.status)}</text>
            </>}
          </g>
        )
      })}
      {/* withdrawals: customer -> request -> destination */}
      {wdNodes.map((w) => {
        const a = pos[w.raw.source], dest = pos[w.raw.target]
        const requested = w.raw.status !== 'broadcast'
        return (
          <g key={w.id} className="node" opacity={fade(onE(w.raw.id))} onClick={() => onSelect({ kind: 'edge', id: w.raw.id })}>
            {a && <Edge a={a} b={w} color={C.line} width={2} />}
            {dest && <>
              <Edge a={w} b={dest} color={requested ? C.text2 : C.line} width={2} dash={requested ? '7 5' : undefined} />
              <text x={(w.x + dest.x) / 2} y={w.y - 22} textAnchor="middle" fontSize={10.5} fill={C.text2}>{usdt(w.raw.amount_minor).replace('.00 ', ' ')} ·</text>
              <text x={(w.x + dest.x) / 2} y={w.y - 9} textAnchor="middle" fontSize={10.5} fill={C.text2}>{t(requested ? 'Requested' : 'Broadcast')}</text>
            </>}
          </g>
        )
      })}
      {/* on-chain history */}
      {chainEdges.map((e: Json) => {
        const a = pos[e.source], b = pos[e.target]
        if (!a || !b || a.col !== b.col) return null
        return (
          <g key={e.id} className="node" opacity={fade(onE(e.id))} onClick={() => onSelect({ kind: 'edge', id: e.id })}>
            <Edge a={a} b={b} color={C.gray} width={1.6} dash="2 4" />
            <text x={a.x - 8} y={(a.y + b.y) / 2 - 2} textAnchor="end" fontSize={10.5} fill={C.text2}>{t('Historical')} ·</text>
            <text x={a.x - 8} y={(a.y + b.y) / 2 + 12} textAnchor="end" fontSize={10.5} fill={C.text2}>{usdt(e.amount_minor).replace('.00 ', ' ')}</text>
          </g>
        )
      })}

      {/* nodes */}
      {Object.values(pos).map((p) => {
        const n = p.raw
        const reported = p.role !== 'withdrawal' && n.signals?.length > 0
        const labelled = p.role !== 'withdrawal' && n.labels?.length > 0
        const merchant = p.id === merchantId
        const inCase = p.role === 'withdrawal' || n.in_case
        const icon = p.role === 'customer' || p.role === 'withdrawal' ? 'user' : p.role === 'bank' ? (merchant ? 'store' : 'bank') : 'file'
        const solid = inCase && !merchant && p.role !== 'destination' && !labelled && !reported
        const name = p.role === 'withdrawal' ? (n.label?.split(' ')[0] ?? shortId(n.id)) : p.role === 'bank' ? bankLabel(n.id) : p.role === 'customer' ? shortId(n.id) : ''
        const sub = t(merchant ? 'Merchant' : p.role === 'destination' ? 'Destination' : labelled ? 'Labelled address' : p.role === 'bank' && !n.in_case && depth[n.id] === 0 ? 'Source account' : '')
        const selKey = p.role === 'withdrawal' ? isSel('edge', n.id) : isSel('node', p.id)
        return (
          <g key={p.id} className="node" opacity={fade(p.role === 'withdrawal' ? onE(n.id) : onN(p.id))} onClick={(ev) => { ev.stopPropagation(); onSelect(p.role === 'withdrawal' ? { kind: 'edge', id: n.id } : { kind: 'node', id: p.id }) }}>
            {selKey && <circle cx={p.x} cy={p.y} r={30} fill="none" stroke={C.teal} strokeWidth={2} strokeDasharray="3 3" />}
            <circle cx={p.x} cy={p.y} r={22} fill={reported ? '#fff8e8' : solid ? C.tealDark : '#fff'} stroke={reported ? '#e2b04a' : flagged(n) ? C.amber : C.teal} strokeWidth={reported ? 3 : 2} />
            <IconAt name={icon} x={p.x} y={p.y} color={solid ? '#fff' : C.tealDark} />
            {name && <text x={p.x} y={p.y + 38} textAnchor="middle" fontSize={12.5} fontWeight={700} fill={C.text}>{name}</text>}
            {sub && <text x={p.x} y={p.y + (name ? 53 : 38)} textAnchor="middle" fontSize={11.5} fill={C.text2}>{sub}</text>}
            {reported && <Chip x={p.x} y={p.y + 52} text={t('Reported')} />}
            {p.role === 'withdrawal' && n.status !== 'broadcast' && <Chip x={p.x} y={p.y + 52} text={t(n.status === 'held_for_review' ? 'Held for review' : n.status === 'released' ? 'Released' : 'Requested')} />}
            {p.role === 'withdrawal' && n.status === 'broadcast' && <Chip x={p.x} y={p.y + 52} text={t('Broadcast')} bad />}
          </g>
        )
      })}
    </svg>
  )
}

function Edge({ a, b, color, width, dash }: { a: Pt; b: Pt; color: string; width: number; dash?: string }) {
  // Shorten so the arrow stops at the node circle.
  const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1
  const sx = a.x + (dx / len) * 24, sy = a.y + (dy / len) * 24
  const ex = b.x - (dx / len) * 26, ey = b.y - (dy / len) * 26
  return <line x1={sx} y1={sy} x2={ex} y2={ey} stroke={color} strokeWidth={width} strokeDasharray={dash} markerEnd={`url(#arr-${color === C.gray || color === C.text2 ? 'g' : 't'})`} />
}

function EdgeLabel({ a, b, text }: { a: Pt; b: Pt; text: string }) {
  const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2
  return <text x={mx} y={my - 8} textAnchor="middle" fontSize={11.5} fill={C.text2} stroke="#eef5f7" strokeWidth={4} paintOrder="stroke">{text}</text>
}

function Chip({ x, y, text, bad }: { x: number; y: number; text: string; bad?: boolean }) {
  const w = text.length * 6.6 + 18
  return <g><rect x={x - w / 2} y={y - 11} width={w} height={20} rx={5} fill={bad ? '#fbe7e6' : C.amberSoft} stroke={bad ? '#e8b1b1' : '#f0cf9c'} />
    <text x={x} y={y + 3} textAnchor="middle" fontSize={11} fontWeight={600} fill={bad ? '#b83232' : C.amber}>{text}</text></g>
}

function LaneTitle({ x, label, icon }: { x: number; label: string; icon: string }) {
  return <g><IconAt name={icon} x={x - label.length * 5 - 14} y={32} color={C.tealDark} size={18} />
    <text x={x - label.length * 5 + 2} y={38} fontSize={16} fontWeight={700} fill={C.text}>{label}</text></g>
}

const ICON_PATHS: Record<string, string> = {
  bank: 'M3 10h18M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 21h18M12 3l9 5H3z',
  store: 'M4 10v10h16V10M3 4h18l-1.5 6h-15zM9 20v-5h6v5',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 20.5c1.2-3.6 4-5.5 7.5-5.5s6.3 1.9 7.5 5.5',
  file: 'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6',
  swap: 'M4 8h15M15 4l4 4-4 4M20 16H5M9 12l-4 4 4 4',
  cube: 'M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9',
}

function IconAt({ name, x, y, color, size = 20 }: { name: string; x: number; y: number; color: string; size?: number }) {
  const s = size / 24
  return <path d={ICON_PATHS[name]} transform={`translate(${x - size / 2} ${y - size / 2}) scale(${s})`} fill="none" stroke={color} strokeWidth={1.8 / s} strokeLinecap="round" strokeLinejoin="round" />
}
