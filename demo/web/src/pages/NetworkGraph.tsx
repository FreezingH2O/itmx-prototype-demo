import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { Json } from '../api'
import { shortId, thb, usdt } from '../format'
import type { Path, Sel } from '../graphPath'
import { t } from '../i18n'

// Group titles are stored in English; "Hop 2" style titles carry their number.
const tt = (s: string) => (s.startsWith('Hop ') ? t('Hop {n}', { n: s.slice(4) }) : t(s))

// Network graph for large runs. Accounts are grouped by stage (source, reported, hop 1..3+ split
// into pass-through / holding, exchange, withdrawals, chain). A closed group is one card; opening it
// (click, or zoom in over it) lays its accounts out in a grid. The box never grows with the data:
// it is a fixed-height viewport with zoom and pan, fitted automatically until the user moves it.

// Layout units are screen pixels at zoom 1.
const CARD_W = 150
const CARD_H = 86
const CELL_W = 64
const CELL_H = 58
const PAD = 12
const HEAD = 36
const COL_GAP = 58
const GROUP_GAP = 22
const R = 13              // account node radius
const ZOOM_OPEN = 1.6     // zooming in past this over a closed group opens it
const ZOOM_CLOSE = 0.75   // zooming out below this closes the groups that zooming opened
const USDT_THB = 35.2     // only to size USDT edges against THB edges

const C = {
  teal: '#12797d', tealDark: '#0d5d63', tealSoft: '#e2f2f1', edge: '#8fb3b6', gray: '#9aa8b0', text: '#0c1f2b',
  text2: '#475965', card: '#ffffff', frame: '#f3f8f9', border: '#c6d4d8', amber: '#c26a0a', amberSoft: '#fff4e3',
  report: '#e2b04a', reportSoft: '#fff8e8', bad: '#b83232', badSoft: '#fbe7e6', path: '#d9480f',
}

const STAGE_TITLE: Record<string, [string, string]> = {
  source: ['Paid in', 'Source accounts'], reported: ['Reported', 'Reported accounts'],
  settlement: ['Settlement', 'No verified link'], customer: ['Exchange', 'Customers'],
  withdrawal: ['Exchange', 'Withdrawals'], chain: ['Chain', 'Addresses'],
}

type Grp = {
  key: string; title: [string, string]; stage: string; order: number; members: Json[]
  open: boolean; x: number; y: number; w: number; h: number; cols: number
}
type End = { key: string; x: number; y: number; member: boolean }

function groupOf(n: Json): { key: string; title: [string, string]; order: number } {
  const s: string = n.stage
  if (s.startsWith('hop')) {
    const hop = s === 'hop3' ? '3+' : s.slice(3)
    if (n.behaviour === 'pass_through') return { key: `${s}/pass`, title: [`Hop ${hop}`, 'Pass-through'], order: 0 }
    const big = (n.remaining_minor ?? 0) >= 5_000_000
    return { key: `${s}/${big ? 'big' : 'small'}`, title: [`Hop ${hop}`, big ? 'Holding ≥ ฿50k' : 'Holding < ฿50k'], order: big ? 1 : 2 }
  }
  return { key: s, title: STAGE_TITLE[s] ?? [s, ''], order: 0 }
}

function layout(graph: Json, open: Set<string>) {
  const byKey = new Map<string, Grp>()
  for (const n of graph.nodes) {
    const { key, title, order } = groupOf(n)
    let g = byKey.get(key)
    if (!g) {
      g = { key, title, order, stage: n.stage, members: [], open: open.has(key), x: 0, y: 0, w: CARD_W, h: CARD_H, cols: 1 }
      byKey.set(key, g)
    }
    g.members.push(n)
  }
  for (const g of byKey.values()) {
    if (!g.open) continue
    g.cols = Math.max(2, Math.min(8, Math.ceil(Math.sqrt(g.members.length / 1.4))))
    g.w = Math.max(CARD_W, g.cols * CELL_W + 2 * PAD)
    g.h = HEAD + Math.ceil(g.members.length / g.cols) * CELL_H + PAD
  }
  const stages: string[] = graph.stages ?? []
  const cols = stages.map((s) => [...byKey.values()].filter((g) => g.stage === s).sort((a, b) => a.order - b.order))
    .filter((c) => c.length)
  const heights = cols.map((c) => c.reduce((s, g) => s + g.h, 0) + GROUP_GAP * (c.length - 1))
  const H = Math.max(CARD_H, ...heights)
  const pos = new Map<string, { x: number; y: number }>()
  const groupOfNode = new Map<string, Grp>()
  let x = 0
  cols.forEach((col, i) => {
    const w = Math.max(...col.map((g) => g.w))
    let y = (H - heights[i]) / 2
    for (const g of col) {
      g.x = x + (w - g.w) / 2
      g.y = y
      y += g.h + GROUP_GAP
      const inner = g.cols * CELL_W
      g.members.forEach((n, j) => {
        groupOfNode.set(n.id, g)
        if (g.open) pos.set(n.id, { x: g.x + (g.w - inner) / 2 + (j % g.cols) * CELL_W + CELL_W / 2, y: g.y + HEAD + Math.floor(j / g.cols) * CELL_H + 18 })
      })
    }
    x += w + COL_GAP
  })
  return { groups: [...byKey.values()], pos, groupOfNode, W: Math.max(CARD_W, x - COL_GAP), H }
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))
const thbValue = (e: Json) => (e.asset === 'USDT' ? (e.amount_minor ?? 0) / 1e6 * USDT_THB : (e.amount_minor ?? 0) / 100)
const money = (asset: string, minor: number) => (asset === 'USDT' ? usdt(minor) : thb(minor))

type Props = { graph: Json; sel: Sel; path: Path | null; onSelect: (s: Sel) => void; merchantId?: string; height?: number }

export default function NetworkGraph({ graph, sel, path, onSelect, merchantId, height = 560 }: Props) {
  const wrap = useRef<HTMLDivElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const [size, setSize] = useState({ w: 900, h: height })
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [view, setView] = useState({ k: 1, x: 0, y: 0 })
  const touched = useRef(false)          // the user zoomed, panned or opened a group: stop auto-fitting
  const zoomOpened = useRef(new Set<string>())
  const wheelAt = useRef<{ cx: number; cy: number } | null>(null)
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null)
  const [dragging, setDragging] = useState(false)

  const L = useMemo(() => layout(graph, open), [graph, open])
  const latest = useRef({ L, open, graph })
  useLayoutEffect(() => { latest.current = { L, open, graph } })

  useLayoutEffect(() => {
    const el = wrap.current
    if (!el) return
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const fitTo = useCallback((W: number, H: number, ox = 0, oy = 0) => {
    const k = clamp(Math.min((size.w - 32) / W, (size.h - 32) / H), 0.08, 1.4)
    setView({ k, x: (size.w - W * k) / 2 - ox * k, y: (size.h - H * k) / 2 - oy * k })
  }, [size])
  const fit = useCallback(() => fitTo(L.W, L.H), [fitTo, L.W, L.H])
  useEffect(() => { if (!touched.current) fit() }, [fit])

  // Open or close groups, keeping the first group's top-left corner where it is on screen.
  const setGroups = useCallback((keys: string[], on: boolean, byZoom = false) => {
    const { L: cur, open: o, graph: g } = latest.current
    const next = new Set(o)
    for (const k of keys) {
      if (on) next.add(k); else next.delete(k)
      if (byZoom && on) zoomOpened.current.add(k); else zoomOpened.current.delete(k)
    }
    const anchor = cur.groups.find((x) => x.key === keys[0])
    const after = anchor && layout(g, next).groups.find((x) => x.key === anchor.key)
    touched.current = true
    if (anchor && after) setView((v) => ({ ...v, x: v.x + (anchor.x - after.x) * v.k, y: v.y + (anchor.y - after.y) * v.k }))
    setOpen(next)
  }, [])

  // Wheel zoom around the cursor (non-passive so the page does not scroll).
  useEffect(() => {
    const el = svg.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const cx = e.clientX - r.left, cy = e.clientY - r.top
      touched.current = true
      wheelAt.current = { cx, cy }
      setView((v) => {
        const k = clamp(v.k * Math.exp(-e.deltaY * 0.0015), 0.08, 4)
        return { k, x: cx - (cx - v.x) * (k / v.k), y: cy - (cy - v.y) * (k / v.k) }
      })
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  // Semantic zoom: zoomed in over a closed group opens it; zooming back out closes those again.
  useEffect(() => {
    const at = wheelAt.current
    if (!at) return
    if (view.k >= ZOOM_OPEN) {
      const lx = (at.cx - view.x) / view.k, ly = (at.cy - view.y) / view.k
      const g = latest.current.L.groups.find((g) => !g.open && lx >= g.x && lx <= g.x + g.w && ly >= g.y && ly <= g.y + g.h)
      if (g) setGroups([g.key], true, true)
    } else if (view.k < ZOOM_CLOSE && zoomOpened.current.size) {
      setGroups([...zoomOpened.current], false)
    }
  }, [view.k]) // eslint-disable-line react-hooks/exhaustive-deps -- react to zoom only, not to panning

  const zoomBy = (f: number) => {
    touched.current = true
    wheelAt.current = null
    setView((v) => {
      const k = clamp(v.k * f, 0.08, 4), cx = size.w / 2, cy = size.h / 2
      return { k, x: cx - (cx - v.x) * (k / v.k), y: cy - (cy - v.y) * (k / v.k) }
    })
  }

  // Per-node amounts for group totals and tooltips.
  const flows = useMemo(() => {
    const m = new Map<string, { in: number; out: number; inUsdt: number }>()
    const get = (id: string) => m.get(id) ?? (m.set(id, { in: 0, out: 0, inUsdt: 0 }), m.get(id)!)
    for (const e of graph.edges) {
      if (e.asset === 'USDT') { get(e.target).inUsdt += e.amount_minor ?? 0; continue }
      get(e.source).out += e.amount_minor ?? 0
      get(e.target).in += e.amount_minor ?? 0
    }
    return m
  }, [graph])
  const groupTotal = (g: Grp): [string, number] => {
    if (g.stage === 'withdrawal' || g.stage === 'chain') return ['USDT', g.members.reduce((s, n) => s + (flows.get(n.id)?.inUsdt ?? 0), 0)]
    if (g.stage === 'source') return ['THB', g.members.reduce((s, n) => s + (flows.get(n.id)?.out ?? 0), 0)]
    return ['THB', g.members.reduce((s, n) => s + (flows.get(n.id)?.in ?? 0), 0)]
  }

  // Resolve each edge end to an account (open group or on the selected path) or to its group card.
  const end = (id: string, side: 'out' | 'in'): End | null => {
    const p = L.pos.get(id)
    if (p) return { key: id, x: p.x + (side === 'out' ? R : -R), y: p.y, member: true }
    const g = L.groupOfNode.get(id)
    return g ? { key: g.key, x: side === 'out' ? g.x + g.w : g.x, y: g.y + g.h / 2, member: false } : null
  }
  const drawn = new Map<string, { a: End; b: End; ids: string[]; value: number; count: number; asset: string; amount: number; kinds: Set<string>; status: Set<string>; onPath: boolean }>()
  for (const e of graph.edges) {
    const a = end(e.source, 'out'), b = end(e.target, 'in')
    if (!a || !b || a.key === b.key) continue
    const usd = e.asset === 'USDT'
    const key = `${a.key}>${b.key}|${usd ? 'u' : 't'}`
    let d = drawn.get(key)
    if (!d) { d = { a, b, ids: [], value: 0, count: 0, asset: usd ? 'USDT' : 'THB', amount: 0, kinds: new Set(), status: new Set(), onPath: false }; drawn.set(key, d) }
    d.ids.push(e.id)
    d.value += thbValue(e)
    d.amount += e.amount_minor ?? 0
    d.count += e.count ?? 1
    d.kinds.add(e.kind)
    d.status.add(e.status)
    if (path?.edges.has(e.id)) d.onPath = true
  }
  const pathCount = (g: Grp) => (path ? g.members.filter((n) => path.nodes.has(n.id)).length : 0)
  const pathGroups = path ? L.groups.filter((g) => !g.open && pathCount(g) > 0).map((g) => g.key) : []
  const allOpen = L.groups.length > 0 && L.groups.every((g) => g.open)

  const onEdge = (ids: string[], a: End, b: End) => {
    if (ids.length === 1) { onSelect({ kind: 'edge', id: ids[0] }); return }
    const closed = [a, b].filter((x) => !x.member).map((x) => x.key)   // a bundle: open its groups to see each transfer
    if (closed.length) setGroups(closed, true)
  }
  const pointerDown = (e: React.PointerEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false }
    wheelAt.current = null
    ;(e.target as Element).setPointerCapture(e.pointerId)
  }
  const pointerMove = (e: React.PointerEvent) => {
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.x, dy = e.clientY - d.y
    if (!d.moved && Math.abs(dx) + Math.abs(dy) > 3) { d.moved = true; touched.current = true; setDragging(true) }
    if (d.moved) setView((v) => ({ ...v, x: d.vx + dx, y: d.vy + dy }))
  }
  const pointerUp = () => {
    if (drag.current && !drag.current.moved) onSelect(null)   // click on empty space clears the path
    drag.current = null
    setDragging(false)
  }

  const dim = !!path
  const edgeList = [...drawn.values()].sort((x, y) => Number(x.onPath) - Number(y.onPath))   // path drawn on top
  const labelPath = dim && edgeList.filter((d) => d.onPath).length <= 40

  return (
    <div ref={wrap} className="net-graph" style={{ height }}>
      <svg ref={svg} width={size.w} height={size.h} role="img" aria-label="Money-flow network graph">
        <defs>
          {[['t', C.teal], ['g', C.edge], ['p', C.path], ['f', '#d5dde0']].map(([k, col]) => (
            <marker key={k} id={`na-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M0 0L10 5L0 10z" fill={col} />
            </marker>
          ))}
        </defs>
        <rect x={0} y={0} width={size.w} height={size.h} fill="transparent" style={{ cursor: dragging ? 'grabbing' : 'grab' }}
          onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} />
        <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
          {/* stage labels */}
          {L.groups.filter((g, i, all) => all.findIndex((x) => x.stage === g.stage) === i).map((g) => (
            <text key={`st-${g.stage}`} x={g.x + g.w / 2} y={-14} textAnchor="middle" fontSize={11 / Math.max(view.k, 0.5)} fontWeight={700} fill={C.text2} style={{ textTransform: 'uppercase', letterSpacing: 0.6 }}>
              {g.stage.startsWith('hop') ? t('Hop {n}', { n: g.stage === 'hop3' ? '3+' : g.stage.slice(3) }) : tt(STAGE_TITLE[g.stage]?.[0] ?? g.stage)}
            </text>
          ))}

          {/* group frames and cards */}
          {L.groups.map((g) => {
            const pc = pathCount(g)
            const [asset, total] = groupTotal(g)
            const reported = g.members.filter((n) => n.signals?.length).length
            if (g.open) return (
              <g key={g.key}>
                <rect x={g.x} y={g.y} width={g.w} height={g.h} rx={12} fill={C.frame} stroke={pc ? C.path : C.border} strokeWidth={pc ? 2 : 1} strokeDasharray={pc ? undefined : '4 3'} />
                <g className="node" onClick={() => setGroups([g.key], false)}>
                  <text x={g.x + PAD} y={g.y + 22} fontSize={12} fontWeight={700} fill={C.text}>{tt(g.title[0])} · {tt(g.title[1])} ({g.members.length})</text>
                  <text x={g.x + g.w - PAD} y={g.y + 22} textAnchor="end" fontSize={12} fill={C.teal}>{t('close')} −</text>
                </g>
              </g>
            )
            return (
              <g key={g.key} className="node" onClick={() => setGroups([g.key], true)} opacity={dim && !pc ? 0.45 : 1}>
                <title>{`${g.title.map(tt).join(' · ')}: ${g.members.length} · ${money(asset, total)}. ${t('Click or zoom in to open.')}`}</title>
                <rect x={g.x} y={g.y} width={g.w} height={g.h} rx={12} fill={pc ? C.amberSoft : C.card} stroke={pc ? C.path : C.border} strokeWidth={pc ? 2.5 : 1.2} />
                <text x={g.x + 12} y={g.y + 20} fontSize={11} fontWeight={700} fill={C.text2} style={{ textTransform: 'uppercase', letterSpacing: 0.5 }}>{tt(g.title[0])}</text>
                <text x={g.x + 12} y={g.y + 36} fontSize={12.5} fontWeight={600} fill={C.text}>{tt(g.title[1])}</text>
                <text x={g.x + 12} y={g.y + 64} fontSize={22} fontWeight={700} fill={C.tealDark}>{g.members.length}</text>
                <text x={g.x + 14 + String(g.members.length).length * 13} y={g.y + 64} fontSize={11} fill={C.text2}>{t(g.members.length === 1 ? 'account' : g.stage === 'withdrawal' ? 'requests' : 'accounts')}</text>
                <text x={g.x + 12} y={g.y + 79} fontSize={10.5} fill={C.text2}>{money(asset, total)}</text>
                <text x={g.x + g.w - 12} y={g.y + 20} textAnchor="end" fontSize={14} fontWeight={700} fill={C.teal}>+</text>
                {reported > 0 && g.stage !== 'reported' && <text x={g.x + g.w - 12} y={g.y + 64} textAnchor="end" fontSize={10.5} fontWeight={600} fill={C.amber}>{t('{n} reported', { n: reported })}</text>}
                {pc > 0 && <g><rect x={g.x + g.w - 74} y={g.y + g.h - 10} width={70} height={18} rx={9} fill={C.path} />
                  <text x={g.x + g.w - 39} y={g.y + g.h + 3} textAnchor="middle" fontSize={10.5} fontWeight={700} fill="#fff">{t('{n} on path', { n: pc })}</text></g>}
              </g>
            )
          })}

          {/* edges */}
          {edgeList.map((d) => {
            const { a, b } = d
            const dx = b.x > a.x ? Math.max(28, (b.x - a.x) * 0.5) : 90
            const p = `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`
            const w = 1.2 + Math.min(6, Math.log10(1 + d.value / 2000) * 1.6)
            const selected = sel?.kind === 'edge' && d.ids.includes(sel.id)
            const color = d.onPath ? C.path : dim ? '#d5dde0' : d.kinds.has('deposit') || d.kinds.has('withdrawal') ? C.teal : C.edge
            const dash = d.status.has('candidate') || d.status.has('requested') ? '7 5' : d.status.has('unresolved') ? '2 5' : undefined
            const marker = d.onPath ? 'p' : dim ? 'f' : color === C.teal ? 't' : 'g'
            const label = `${d.count > 1 ? `${d.count} × ` : ''}${money(d.asset, d.amount)}`
            return (
              <g key={`${a.key}>${b.key}${d.asset}`} className="node" onClick={() => onEdge(d.ids, a, b)}>
                <title>{`${label}${d.ids.length > 1 ? ` · ${d.ids.length} account pairs: click to open the groups` : ' · click to trace its path'}`}</title>
                <path d={p} fill="none" stroke="transparent" strokeWidth={Math.max(12, w + 8) / Math.max(view.k, 0.4)} />
                <path d={p} fill="none" stroke={color} strokeWidth={(d.onPath ? w + 1.5 : w) + (selected ? 2 : 0)} strokeDasharray={dash}
                  opacity={dim && !d.onPath ? 0.6 : 0.9} markerEnd={`url(#na-${marker})`} />
                {labelPath && d.onPath && (
                  <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 6} textAnchor="middle" fontSize={10.5} fontWeight={600} fill={C.path}
                    stroke="#fff" strokeWidth={3.5} paintOrder="stroke">{label}</text>
                )}
              </g>
            )
          })}

          {/* accounts inside open groups */}
          {L.groups.filter((g) => g.open).flatMap((g) => g.members.map((n) => {
            const p = L.pos.get(n.id)!
            const onPath = path?.nodes.has(n.id)
            const isSel = sel?.kind === 'node' && sel.id === n.id
            const reported = n.signals?.length > 0
            const merchant = n.id === merchantId
            const wd = n.kind === 'withdrawal'
            const stroke = onPath ? C.path : reported ? C.report : n.labels?.length ? C.amber : wd && n.status === 'broadcast' ? C.bad : C.teal
            const fill = reported ? C.reportSoft : merchant ? C.tealSoft : wd && n.status === 'held' ? C.amberSoft : '#fff'
            const f = flows.get(n.id)
            const tip = [n.label, n.reports ? `${n.reports} report${n.reports > 1 ? 's' : ''}` : '',
              wd ? `${n.status} · ${usdt(n.amount_minor)}` : '',
              f?.in ? `received ${thb(f.in)}` : '', f?.out ? `sent ${thb(f.out)}` : '',
              n.remaining_minor ? `still holds ${thb(n.remaining_minor)}` : ''].filter(Boolean).join(' · ')
            return (
              <g key={n.id} className="node" opacity={dim && !onPath ? 0.3 : 1} onClick={(ev) => { ev.stopPropagation(); onSelect({ kind: 'node', id: n.id }) }}>
                <title>{tip}</title>
                {isSel && <circle cx={p.x} cy={p.y} r={R + 6} fill="none" stroke={C.path} strokeWidth={2} strokeDasharray="3 3" />}
                {wd
                  ? <rect x={p.x - R} y={p.y - R + 3} width={R * 2} height={R * 2 - 6} rx={5} fill={fill} stroke={stroke} strokeWidth={onPath ? 2.5 : 1.6} />
                  : <circle cx={p.x} cy={p.y} r={R} fill={fill} stroke={stroke} strokeWidth={onPath ? 2.5 : reported ? 2.2 : 1.6} />}
                {merchant && <text x={p.x} y={p.y + 4} textAnchor="middle" fontSize={11} fontWeight={700} fill={C.tealDark}>M</text>}
                {n.hub && <text x={p.x} y={p.y + 4} textAnchor="middle" fontSize={10} fontWeight={700} fill={C.tealDark}>H</text>}
                <text x={p.x} y={p.y + R + 12} textAnchor="middle" fontSize={9.5} fontWeight={onPath ? 700 : 500} fill={onPath ? C.path : C.text}>{shortId(n.id)}</text>
              </g>
            )
          }))}
        </g>
      </svg>
      <div className="net-tools">
        <button onClick={() => zoomBy(1.25)} aria-label={t('Zoom in')}>+</button>
        <button onClick={() => zoomBy(0.8)} aria-label={t('Zoom out')}>−</button>
        <button onClick={() => { touched.current = false; fit() }}>{t('Fit')}</button>
        <button onClick={() => setGroups(L.groups.map((g) => g.key), !allOpen)}>{t(allOpen ? 'Close all' : 'Open all')}</button>
        {pathGroups.length > 0 && <button className="on" onClick={() => setGroups(pathGroups, true)}>{t('Open path groups')}</button>}
      </div>
      <div className="net-hint">{t('Scroll to zoom · drag to pan · click a group to open it · click a transfer or account to trace its path')}</div>
    </div>
  )
}
