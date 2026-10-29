import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import App from './App'
import type { Api } from './api'
import { ApiError } from './api'
import type { Break, Page, RunSummary, Upload } from './types'

const bankUpload: Upload = {
  id: 1,
  kind: 'bank',
  filename: 'bank_statement.csv',
  sha256: 'a'.repeat(64),
  row_count: 4862,
  created_at: '2026-10-28T09:00:00Z',
}
const ledgerUpload: Upload = { ...bankUpload, id: 2, kind: 'ledger', filename: 'ledger.csv', row_count: 4896 }

const summary: RunSummary = {
  id: 7,
  created_at: '2026-10-28T09:01:00Z',
  bank_upload: bankUpload,
  ledger_upload: ledgerUpload,
  date_window_days: 3,
  max_edits: 2,
  bank_count: 4862,
  ledger_count: 4896,
  matched_count: 4601,
  match_rate: 0.943,
  duration_ms: 412,
  matches_by_rule: { exact_reference: 4297, fuzzy_reference: 143, amount_date: 161 },
  breaks_by_type: [
    { type: 'missing_in_bank', open: 177, resolved: 0, open_amount: '1234567.89' },
    { type: 'missing_in_ledger', open: 144, resolved: 0, open_amount: '987654.32' },
    { type: 'amount_mismatch', open: 96, resolved: 0, open_amount: '2400.00' },
    { type: 'duplicate', open: 43, resolved: 0, open_amount: '56000.00' },
  ],
  open_breaks: 460,
  open_amount: '2280622.21',
}

const mismatch: Break = {
  id: 31,
  run_id: 7,
  type: 'amount_mismatch',
  status: 'open',
  reason: 'Same reference INV1001, but the bank shows 4,985.00 and the ledger 5,000.00: the bank is 15.00 lower.',
  amount: '15.00',
  difference: '-15.00',
  bank: { id: 3, row: 12, date: '2026-10-02', amount: '4985.00', reference: 'INV-1001', description: 'NEFT CR ACME TRADERS' },
  ledger: { id: 9, row: 10, date: '2026-10-01', amount: '5000.00', reference: 'INV-1001', description: 'Receipt from Acme Traders' },
  resolution_note: null,
  resolved_at: null,
}

function page(items: Break[]): Page<Break> {
  return { items, total: items.length, limit: 25, offset: 0 }
}

function fakeApi(overrides: Partial<Api> = {}): Api {
  return {
    listRuns: vi.fn().mockResolvedValue([summary]),
    getRun: vi.fn().mockResolvedValue(summary),
    listBreaks: vi.fn().mockResolvedValue(page([mismatch])),
    resolveBreak: vi.fn().mockResolvedValue({ ...mismatch, status: 'resolved', resolution_note: 'Bank charges' }),
    upload: vi.fn(),
    startRun: vi.fn(),
    ...overrides,
  }
}

describe('the dashboard', () => {
  it('shows the latest run: match rate, breaks by type and the open exceptions', async () => {
    const api = fakeApi()
    render(<App api={api} />)

    expect(await screen.findByText('94.30%')).toBeInTheDocument()
    expect(screen.getByText('₹22,80,622.21 to review')).toBeInTheDocument()
    const breakdown = screen.getByRole('region', { name: 'Open breaks by type' })
    expect(within(breakdown).getByText('Missing in bank')).toBeInTheDocument()
    expect(within(breakdown).getByText('177')).toBeInTheDocument()
    const queue = screen.getByRole('region', { name: 'Exception queue' })
    expect(await within(queue).findByText(/the bank is 15.00 lower/)).toBeInTheDocument()
    expect(within(queue).getByText('₹4,985.00')).toBeInTheDocument()
    expect(api.listBreaks).toHaveBeenCalledWith(7, { type: undefined, status: 'open', limit: 25, offset: 0 })
  })

  it('filters the exception queue when a break type is picked', async () => {
    const api = fakeApi()
    render(<App api={api} />)
    const breakdown = await screen.findByRole('region', { name: 'Open breaks by type' })

    await userEvent.click(within(breakdown).getByRole('button', { name: /Duplicate/ }))

    await waitFor(() =>
      expect(api.listBreaks).toHaveBeenLastCalledWith(7, { type: 'duplicate', status: 'open', limit: 25, offset: 0 }),
    )
    expect(screen.getByRole('combobox', { name: 'Break type' })).toHaveValue('duplicate')
  })

  it('resolves a break with a note, then refreshes the run', async () => {
    const api = fakeApi()
    render(<App api={api} />)
    const queue = await screen.findByRole('region', { name: 'Exception queue' })

    await userEvent.click(await within(queue).findByRole('button', { name: 'Resolve' }))
    await userEvent.type(within(queue).getByLabelText('Resolution note'), 'Bank charges, booked to fees')
    await userEvent.click(within(queue).getByRole('button', { name: 'Mark resolved' }))

    expect(api.resolveBreak).toHaveBeenCalledWith(31, 'Bank charges, booked to fees')
    await waitFor(() => expect(api.getRun).toHaveBeenCalledTimes(2))
  })

  it('lists every problem when an upload is refused', async () => {
    const refused = new ApiError(422, {
      detail: '2 rows have problems, so nothing was stored.',
      code: 'invalid_file',
      errors: ["row 2: date '2026-13-01' is not a date in a supported format", "row 3: amount 'ten' is not a number"],
    })
    const api = fakeApi({ listRuns: vi.fn().mockResolvedValue([]), upload: vi.fn().mockRejectedValue(refused) })
    render(<App api={api} />)

    await userEvent.click(await screen.findByRole('button', { name: 'New reconciliation' }))
    const form = screen.getByRole('form', { name: 'New reconciliation' })
    const csv = (name: string) => new File(['date,amount\n'], name, { type: 'text/csv' })
    await userEvent.upload(within(form).getByLabelText('Bank statement'), csv('bank.csv'))
    await userEvent.upload(within(form).getByLabelText('Ledger'), csv('ledger.csv'))
    await userEvent.click(within(form).getByRole('button', { name: 'Reconcile' }))

    const alert = await within(form).findByRole('alert')
    expect(alert).toHaveTextContent('Bank statement: 2 rows have problems, so nothing was stored.')
    expect(alert).toHaveTextContent("row 3: amount 'ten' is not a number")
    expect(api.startRun).not.toHaveBeenCalled()
  })

  it('starts a reconciliation from two uploads and shows it', async () => {
    const api = fakeApi({
      listRuns: vi.fn().mockResolvedValue([]),
      upload: vi.fn().mockImplementation((kind: string) => Promise.resolve(kind === 'bank' ? bankUpload : ledgerUpload)),
      startRun: vi.fn().mockResolvedValue(summary),
    })
    render(<App api={api} />)

    expect(await screen.findByText(/No reconciliations yet/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'New reconciliation' }))
    const form = screen.getByRole('form', { name: 'New reconciliation' })
    await userEvent.upload(within(form).getByLabelText('Bank statement'), new File(['x'], 'bank.csv'))
    await userEvent.upload(within(form).getByLabelText('Ledger'), new File(['x'], 'ledger.csv'))
    await userEvent.click(within(form).getByRole('button', { name: 'Reconcile' }))

    expect(await screen.findByText('94.30%')).toBeInTheDocument()
    expect(api.startRun).toHaveBeenCalledWith(1, 2, 3)
  })
})
