import type { Json } from './api'

// End-to-end path of a selected transfer or account through the graph, in time order.
// Downstream: edges leaving the receiver after the money arrived. Upstream: edges into the
// sender before it was sent. Exchange settlement hubs are not walked through (that would join
// unrelated customers); deposit links carry the path into the exchange instead.

export type Sel = { kind: 'edge' | 'node'; id: string } | null
export type Path = { edges: Set<string>; nodes: Set<string>; steps: Json[] }

const first = (e: Json) => Date.parse(e.occurred_at ?? '') || 0
const last = (e: Json) => Date.parse(e.last_at ?? e.occurred_at ?? '') || 0

export function tracePath(graph: Json | null, sel: Sel): Path | null {
  if (!graph || !sel) return null
  const edges: Json[] = graph.edges ?? []
  const hubs = new Set<string>((graph.nodes ?? []).filter((n: Json) => n.hub).map((n: Json) => n.id))
  const out = new Map<string, Json[]>()
  const inn = new Map<string, Json[]>()
  for (const e of edges) {
    if (!out.has(e.source)) out.set(e.source, [])
    if (!inn.has(e.target)) inn.set(e.target, [])
    out.get(e.source)!.push(e)
    inn.get(e.target)!.push(e)
  }
  const keep = new Map<string, Json>()
  const down = (start: Json[]) => {
    const q = [...start]
    while (q.length) {
      const e = q.shift()!
      if (hubs.has(e.target)) continue
      for (const f of out.get(e.target) ?? []) {
        if (!keep.has(f.id) && last(f) >= first(e)) { keep.set(f.id, f); q.push(f) }
      }
    }
  }
  const up = (start: Json[]) => {
    const q = [...start]
    while (q.length) {
      const e = q.shift()!
      if (hubs.has(e.source)) continue
      for (const g of inn.get(e.source) ?? []) {
        if (!keep.has(g.id) && first(g) <= last(e)) { keep.set(g.id, g); q.push(g) }
      }
    }
  }
  if (sel.kind === 'edge') {
    const e = edges.find((x) => x.id === sel.id)
    if (!e) return null
    keep.set(e.id, e)
    down([e])
    up([e])
  } else {
    const outs = out.get(sel.id) ?? []
    const ins = inn.get(sel.id) ?? []
    for (const e of [...outs, ...ins]) keep.set(e.id, e)
    down(outs)
    up(ins)
  }
  const nodes = new Set<string>(sel.kind === 'node' ? [sel.id] : [])
  for (const e of keep.values()) { nodes.add(e.source); nodes.add(e.target) }
  const steps = [...keep.values()].sort((a, b) => first(a) - first(b))
  return { edges: new Set(keep.keys()), nodes, steps }
}
