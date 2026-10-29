import { useEffect, useState } from 'react'

import type { Api } from '../api'
import { ApiError } from '../api'
import { formatCount, formatDate, formatMoney } from '../format'
import type { Break, BreakStatus, BreakType, Page } from '../types'
import { BREAK_LABELS } from '../types'

const PAGE_SIZE = 25
const STATUSES: { value: BreakStatus | undefined; label: string }[] = [
  { value: 'open', label: 'Open' },
  { value: 'resolved', label: 'Resolved' },
  { value: undefined, label: 'All' },
]

interface Props {
  api: Api
  runId: number
  type: BreakType | undefined
  onTypeChange: (type: BreakType | undefined) => void
  onResolved: () => void
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.'
}

function Amount({ value }: { value: string | undefined }) {
  return <td className="num">{value === undefined ? '—' : formatMoney(value)}</td>
}

export function ExceptionQueue({ api, runId, type, onTypeChange, onResolved }: Props) {
  const [status, setStatus] = useState<BreakStatus | undefined>('open')
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<Page<Break> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)

  // Another run or break type starts again from the first page (React's pattern for
  // adjusting state when a prop changes, without an extra effect and render).
  const [shown, setShown] = useState({ runId, type })
  if (shown.runId !== runId || shown.type !== type) {
    setShown({ runId, type })
    setOffset(0)
  }

  useEffect(() => {
    let current = true
    api
      .listBreaks(runId, { type, status, limit: PAGE_SIZE, offset })
      .then((result) => current && (setPage(result), setError(null)))
      .catch((caught: unknown) => current && setError(message(caught)))
    return () => {
      current = false
    }
  }, [api, runId, type, status, offset, reload])

  const resolved = () => {
    setReload((value) => value + 1)
    onResolved()
  }

  return (
    <section className="panel queue" aria-label="Exception queue">
      <header className="queue__header">
        <h2 className="panel__title">Exception queue</h2>
        <div className="queue__filters">
          <select
            aria-label="Break type"
            value={type ?? ''}
            onChange={(event) => onTypeChange((event.target.value || undefined) as BreakType | undefined)}
          >
            <option value="">All break types</option>
            {Object.entries(BREAK_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          <div className="segmented" role="group" aria-label="Status">
            {STATUSES.map((option) => (
              <button
                key={option.label}
                type="button"
                aria-pressed={status === option.value}
                onClick={() => {
                  setStatus(option.value)
                  setOffset(0)
                }}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      </header>
      {error && <p className="alert">{error}</p>}
      {page && page.items.length === 0 && <p className="empty">Nothing to review here.</p>}
      {page && page.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th scope="col">Break</th>
                <th scope="col">Date</th>
                <th scope="col">Reference</th>
                <th scope="col" className="num">
                  Bank
                </th>
                <th scope="col" className="num">
                  Ledger
                </th>
                <th scope="col">Why</th>
                <th scope="col">
                  <span className="visually-hidden">Action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((item) => (
                <BreakRow key={item.id} item={item} api={api} onResolved={resolved} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {page && page.total > 0 && (
        <footer className="pager">
          <span>
            {formatCount(page.offset + 1)}–{formatCount(page.offset + page.items.length)} of{' '}
            {formatCount(page.total)}
          </span>
          <button type="button" disabled={offset === 0} onClick={() => setOffset(offset - PAGE_SIZE)}>
            Previous
          </button>
          <button
            type="button"
            disabled={offset + PAGE_SIZE >= page.total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </button>
        </footer>
      )}
    </section>
  )
}

function BreakRow({ item, api, onResolved }: { item: Break; api: Api; onResolved: () => void }) {
  const [editing, setEditing] = useState(false)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const entry = item.bank ?? item.ledger

  const resolve = async () => {
    setSaving(true)
    try {
      await api.resolveBreak(item.id, note.trim())
      setEditing(false)
      onResolved()
    } catch (caught) {
      setError(caught instanceof ApiError && caught.status === 409 ? 'Already resolved.' : message(caught))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <tr className={item.status === 'resolved' ? 'is-resolved' : undefined}>
        <td>
          <span className={`badge badge--${item.type}`}>{BREAK_LABELS[item.type]}</span>
        </td>
        <td className="nowrap">{entry ? formatDate(entry.date) : '—'}</td>
        <td className="mono">{entry?.reference || '—'}</td>
        <Amount value={item.bank?.amount} />
        <Amount value={item.ledger?.amount} />
        <td className="reason">
          {item.reason}
          {item.resolution_note && <span className="note">Resolved: {item.resolution_note}</span>}
        </td>
        <td>
          {item.status === 'open' && !editing && (
            <button type="button" className="button button--small" onClick={() => setEditing(true)}>
              Resolve
            </button>
          )}
        </td>
      </tr>
      {editing && (
        <tr className="resolve-row">
          <td colSpan={7}>
            <form
              className="resolve"
              onSubmit={(event) => {
                event.preventDefault()
                void resolve()
              }}
            >
              <label>
                Resolution note
                <input
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="e.g. Bank charges of ₹15, booked to fees"
                  maxLength={500}
                  required
                  autoFocus
                />
              </label>
              <button type="submit" className="button" disabled={saving || !note.trim()}>
                Mark resolved
              </button>
              <button type="button" className="button button--quiet" onClick={() => setEditing(false)}>
                Cancel
              </button>
              {error && <span className="alert alert--inline">{error}</span>}
            </form>
          </td>
        </tr>
      )}
    </>
  )
}
