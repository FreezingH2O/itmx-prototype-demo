// Small inline icon set (stroke icons, 24px grid). Colour follows currentColor.
type P = { size?: number; className?: string }

const PATHS: Record<string, string> = {
  bank: 'M3 10h18M5 10v8M9.5 10v8M14.5 10v8M19 10v8M3 21h18M12 3l9 5H3z',
  graph: 'M12 5.5a2.5 2.5 0 1 0 0-.01M5 18.5a2.5 2.5 0 1 0 0-.01M19 18.5a2.5 2.5 0 1 0 0-.01M10.8 7.2 6.3 16.3M13.2 7.2l4.5 9.1M7.5 18.5h9',
  store: 'M4 10v10h16V10M3 4h18l-1.5 6h-15zM9 20v-5h6v5M3 10c1.5 1.4 4.5 1.4 6 0 1.5 1.4 4.5 1.4 6 0 1.5 1.4 4.5 1.4 6 0',
  chart: 'M4 20h16M7 16v-4M12 16V7M17 16v-7',
  file: 'M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6',
  list: 'M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01',
  play: 'M7 4.5v15l12-7.5z',
  pause: 'M8 5v14M16 5v14',
  step: 'M6 5v14l9-7zM18 5v14',
  reset: 'M4 12a8 8 0 1 0 2.4-5.7M4 4v5h5',
  home: 'M4 11l8-7 8 7v9H4zM10 20v-6h4v6',
  present: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM10 8.5v7l6-3.5z',
  expand: 'M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7',
  close: 'M6 6l12 12M18 6 6 18',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  checkCircle: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM8 12.3l2.8 2.7L16 9.6',
  alert: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7.5v5.5M12 16.5h.01',
  info: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5.5M12 7.5h.01',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3.5 2',
  user: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4.5 20.5c1.2-3.6 4-5.5 7.5-5.5s6.3 1.9 7.5 5.5',
  swap: 'M4 8h15M15 4l4 4-4 4M20 16H5M9 12l-4 4 4 4',
  cube: 'M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9',
  database: 'M12 9c4.4 0 8-1.3 8-3s-3.6-3-8-3-8 1.3-8 3 3.6 3 8 3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
  leaf: 'M5 19c0-8 5-13 15-14-1 10-6 15-14 15M5 19l7-7',
  wallet: 'M4 7h15a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a2 2 0 0 1 2-2h11v3M16 13.5h.01',
  lock: 'M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 0 1 7 0v3',
  code: 'M9 8l-4 4 4 4M15 8l4 4-4 4',
  chevronRight: 'M9 6l6 6-6 6',
  chevronDown: 'M6 9l6 6 6-6',
  bolt: 'M13 3 5 13.5h6L10 21l8-10.5h-6z',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 14.5l1.4 1.1-2 3.4-1.7-.6a7.6 7.6 0 0 1-2 1.2L14.8 21h-3.9l-.3-1.6a7.6 7.6 0 0 1-2-1.2l-1.7.6-2-3.4 1.4-1.1a7.4 7.4 0 0 1 0-2.4L4.9 11l2-3.4 1.7.6a7.6 7.6 0 0 1 2-1.2l.3-1.6h3.9l.3 1.6a7.6 7.6 0 0 1 2 1.2l1.7-.6 2 3.4-1.4 1.1a7.4 7.4 0 0 1 0 2.4z',
  send: 'M5 12h14M13 6l6 6-6 6',
  refresh: 'M20 12a8 8 0 1 1-2.4-5.7M20 4v5h-5',
}

export function Icon({ name, size = 18, className }: P & { name: keyof typeof PATHS | string }) {
  const d = PATHS[name] ?? PATHS.info
  const filled = name === 'play' || name === 'step'
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true"
      fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth={filled ? 0 : 1.8}
      strokeLinecap="round" strokeLinejoin="round">
      {filled && name === 'step' ? <><path d="M6 5v14l9-7z" /><path d="M17 5h2v14h-2z" /></> : <path d={d} />}
    </svg>
  )
}

// Brand mark: a suspension bridge linking two pillars (bank side, crypto side).
export function Logo({ size = 64 }: { size?: number }) {
  return (
    <svg width={size} height={size * 0.62} viewBox="0 0 100 62" aria-hidden="true">
      <defs>
        <linearGradient id="lg-cable" x1="0" x2="1">
          <stop offset="0" stopColor="#5fd6cf" /><stop offset="1" stopColor="#2aa7a3" />
        </linearGradient>
      </defs>
      <path d="M4 44 Q 28 10 50 30 Q 72 10 96 44" fill="none" stroke="url(#lg-cable)" strokeWidth="3" strokeLinecap="round" />
      <path d="M28 8v38M72 8v38" stroke="#e8f4f4" strokeWidth="4.5" strokeLinecap="round" />
      <path d="M2 46h96" stroke="#e8f4f4" strokeWidth="3.5" strokeLinecap="round" />
      {[[14, 33], [20, 28], [38, 23], [44, 26], [56, 26], [62, 23], [80, 28], [86, 33]].map(([x, y]) => (
        <path key={x} d={`M${x} ${y}V46`} stroke="#5fd6cf" strokeWidth="1.3" opacity=".8" />
      ))}
      <circle cx="28" cy="6" r="2.4" fill="#5fd6cf" /><circle cx="72" cy="6" r="2.4" fill="#5fd6cf" />
      <path d="M10 54h80" stroke="#5fd6cf" strokeWidth="1.2" opacity=".35" strokeLinecap="round" />
    </svg>
  )
}
