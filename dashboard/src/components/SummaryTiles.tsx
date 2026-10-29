import { formatCount, formatDuration, formatMoney, formatPercent } from '../format'
import type { RunSummary } from '../types'

interface Tile {
  label: string
  value: string
  detail: string
  tone?: 'good' | 'warn'
}

function tiles(summary: RunSummary): Tile[] {
  return [
    {
      label: 'Match rate',
      value: formatPercent(summary.match_rate),
      detail: `${formatCount(summary.matched_count)} pairs matched automatically`,
      tone: 'good',
    },
    {
      label: 'Open breaks',
      value: formatCount(summary.open_breaks),
      detail: `${formatMoney(summary.open_amount)} to review`,
      tone: summary.open_breaks > 0 ? 'warn' : 'good',
    },
    {
      label: 'Bank statement',
      value: formatCount(summary.bank_count),
      detail: summary.bank_upload.filename,
    },
    {
      label: 'Ledger',
      value: formatCount(summary.ledger_count),
      detail: summary.ledger_upload.filename,
    },
    {
      label: 'Matched in',
      value: formatDuration(summary.duration_ms),
      detail: `±${summary.date_window_days} day window, up to ${summary.max_edits} edits`,
    },
  ]
}

export function SummaryTiles({ summary }: { summary: RunSummary }) {
  return (
    <section className="tiles" aria-label="Run summary">
      {tiles(summary).map((tile) => (
        <article key={tile.label} className={`tile ${tile.tone ? `tile--${tile.tone}` : ''}`}>
          <h2 className="tile__label">{tile.label}</h2>
          <p className="tile__value">{tile.value}</p>
          <p className="tile__detail" title={tile.detail}>
            {tile.detail}
          </p>
        </article>
      ))}
    </section>
  )
}
