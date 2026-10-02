import { createContext, useContext } from 'react'
import { TH } from './i18n.th'

// UI language. Strings are written in English in the components and wrapped in t(); the Thai
// table (i18n.th.ts) is keyed by that English text. A missing entry falls back to English.
// Text produced by the engine API (rationales, evidence lines, notices) is not translated.
export type Lang = 'en' | 'th'
const KEY = 'nitmx.lang'
let current: Lang = readLang()
const missing = new Set<string>()

function readLang(): Lang {
  try { return localStorage.getItem(KEY) === 'th' ? 'th' : 'en' } catch { return 'en' }
}

export function getLang(): Lang { return current }

export function storeLang(l: Lang) {
  current = l
  try { localStorage.setItem(KEY, l) } catch { /* storage blocked */ }
}

export function t(en: string, vars?: Record<string, string | number>): string {
  let s = en
  if (current === 'th') {
    const th = TH[en]
    if (th !== undefined) s = th
    else if (import.meta.env.DEV && /[A-Za-z]/.test(en) && !missing.has(en)) { missing.add(en); console.warn('[i18n] missing Thai:', en) }
  }
  return vars ? s.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m)) : s
}

export const LangCtx = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({ lang: current, setLang: () => {} })

// Components that call useLang() re-render on a switch; App calls it, so the whole tree does.
export const useLang = () => useContext(LangCtx)
