import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { LangCtx, getLang, storeLang, useLang, type Lang } from './i18n'

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setState] = useState<Lang>(getLang)
  const setLang = useCallback((l: Lang) => { storeLang(l); setState(l) }, [])
  useEffect(() => { document.documentElement.lang = lang }, [lang])
  return <LangCtx.Provider value={{ lang, setLang }}>{children}</LangCtx.Provider>
}

export function LangToggle() {
  const { lang, setLang } = useLang()
  return (
    <div className="lang-toggle" role="group" aria-label="Language / ภาษา">
      <button aria-pressed={lang === 'en'} onClick={() => setLang('en')} title="English">EN</button>
      <button aria-pressed={lang === 'th'} onClick={() => setLang('th')} title="ภาษาไทย">ไทย</button>
    </div>
  )
}
