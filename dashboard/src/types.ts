// Shapes of the ReconX API's responses. Money arrives as strings ("5000.00") so that no
// amount ever passes through a binary float; it is formatted for display, never summed here.

export type Side = 'bank' | 'ledger'
export type Rule = 'exact_reference' | 'amount_date' | 'fuzzy_reference'
export type BreakType = 'missing_in_bank' | 'missing_in_ledger' | 'amount_mismatch' | 'duplicate'
export type BreakStatus = 'open' | 'resolved'

export interface Upload {
  id: number
  kind: Side
  filename: string
  sha256: string
  row_count: number
  created_at: string
}

export interface Run {
  id: number
  created_at: string
  bank_upload: Upload
  ledger_upload: Upload
  date_window_days: number
  max_edits: number
  bank_count: number
  ledger_count: number
  matched_count: number
  match_rate: number
  duration_ms: number
}

export interface BreakTypeSummary {
  type: BreakType
  open: number
  resolved: number
  open_amount: string
}

export interface RunSummary extends Run {
  matches_by_rule: Record<Rule, number>
  breaks_by_type: BreakTypeSummary[]
  open_breaks: number
  // The money involved in open breaks: the entry's amount, or the difference for a mismatch.
  open_amount: string
}

export interface EntryView {
  id: number
  row: number
  date: string
  amount: string
  reference: string
  description: string
}

export interface Break {
  id: number
  run_id: number
  type: BreakType
  status: BreakStatus
  reason: string
  amount: string
  difference: string | null
  bank: EntryView | null
  ledger: EntryView | null
  resolution_note: string | null
  resolved_at: string | null
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface ApiErrorBody {
  detail: string
  code: string
  errors: string[]
}

export const RULE_LABELS: Record<Rule, string> = {
  exact_reference: 'Exact reference',
  amount_date: 'Amount and date',
  fuzzy_reference: 'Fuzzy reference',
}

export const BREAK_LABELS: Record<BreakType, string> = {
  missing_in_bank: 'Missing in bank',
  missing_in_ledger: 'Missing in ledger',
  amount_mismatch: 'Amount mismatch',
  duplicate: 'Duplicate',
}
