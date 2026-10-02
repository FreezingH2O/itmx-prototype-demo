import { t } from './i18n'

export function money(minor: number | null | undefined, asset = 'THB'): string {
  if (minor === null || minor === undefined) return '-'
  if (asset === 'USDT') return `${(minor / 1_000_000).toLocaleString('en-US', { maximumFractionDigits: 2 })} USDT`
  return `${(minor / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} THB`
}

export function baht(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return '-'
  return `฿${(minor / 100).toLocaleString('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

// bank_c -> Bank C, exchange -> Exchange
export function instName(org: string): string {
  return org === 'exchange' ? t('Exchange') : org.replace(/^bank_(\w)$/, (_, c: string) => t('Bank {c}', { c: c.toUpperCase() }))
}

export function time(iso: string | null | undefined): string {
  if (!iso) return '-'
  return iso.slice(11, 19)
}

export function shortId(ref: string): string {
  const id = ref.split(':').pop() ?? ref
  return id.length > 16 ? `${id.slice(0, 6)}…${id.slice(-4)}` : id
}

export const ACTION_LABEL: Record<string, string> = {
  EXISTING_CONTROLS_ONLY: 'Existing controls only',
  REVIEW_PRIORITY: 'Review priority',
  REQUEST_INFORMATION: 'Request information',
  INSUFFICIENT_EVIDENCE: 'Insufficient evidence',
  RECOMMEND_RESTRICTION_REVIEW: 'Recommend restriction review',
  RECOMMEND_RELEASE_REVIEW: 'Recommend release review',
}

// Compact baht for cards and tables: ฿16,000 (drops .00), ฿17,700.50 otherwise.
export function thb(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return '-'
  const v = minor / 100
  return `฿${v.toLocaleString('en-US', { minimumFractionDigits: Number.isInteger(v) ? 0 : 2, maximumFractionDigits: 2 })}`
}

export function usdt(minor: number | null | undefined): string {
  if (minor === null || minor === undefined) return '-'
  return `${(minor / 1_000_000).toLocaleString('en-US', { maximumFractionDigits: 2 })} USDT`
}

export function hm(iso: string | null | undefined): string {
  return iso ? iso.slice(11, 16) : '-'
}

const REC_STATUS: Record<string, [string, string]> = {
  delivered: ['Awaiting officer', 'amber'],
  acknowledged: ['Acknowledged', 'good'],
  superseded: ['Superseded', ''],
  expired: ['Expired', ''],
}
export function recStatus(s: string): [string, string] {
  const r = REC_STATUS[s]
  return r ? [t(r[0]), r[1]] : [s, '']
}

export const SHORT_ACTION: Record<string, string> = {
  EXISTING_CONTROLS_ONLY: 'Existing controls',
  REVIEW_PRIORITY: 'Priority review',
  REQUEST_INFORMATION: 'Request information',
  INSUFFICIENT_EVIDENCE: 'Insufficient evidence',
  RECOMMEND_RESTRICTION_REVIEW: 'Restriction review',
  RECOMMEND_RELEASE_REVIEW: 'Release review',
}
