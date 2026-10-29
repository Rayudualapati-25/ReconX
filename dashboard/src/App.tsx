import { useEffect, useMemo, useState } from 'react'

import type { Api } from './api'
import { createApi } from './api'
import { Breakdown } from './components/Breakdown'
import { ExceptionQueue } from './components/ExceptionQueue'
import { NewRunForm } from './components/NewRunForm'
import { SummaryTiles } from './components/SummaryTiles'
import { formatCount, formatDate, formatMoney } from './format'
import type { BreakType, Rule, Run, RunSummary } from './types'
import { BREAK_LABELS, RULE_LABELS } from './types'

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.'
}

function runLabel(run: Run): string {
  return `Run ${run.id} · ${run.bank_upload.filename} vs ${run.ledger_upload.filename} · ${formatDate(run.created_at)}`
}

export default function App({ api: given }: { api?: Api }) {
  const api = useMemo(() => given ?? createApi(), [given])
  const [runs, setRuns] = useState<Run[] | null>(null)
  const [runId, setRunId] = useState<number | null>(null)
  const [summary, setSummary] = useState<RunSummary | null>(null)
  const [breakType, setBreakType] = useState<BreakType | undefined>()
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    api
      .listRuns()
      .then((list) => {
        setRuns(list)
        setRunId((current) => current ?? list[0]?.id ?? null)
      })
      .catch((caught: unknown) => setError(message(caught)))
  }, [api])

  useEffect(() => {
    if (runId === null) return
    let current = true
    api
      .getRun(runId)
      .then((result) => current && setSummary(result))
      .catch((caught: unknown) => current && setError(message(caught)))
    return () => {
      current = false
    }
  }, [api, runId, refresh])

  const created = (run: RunSummary) => {
    setRuns((list) => [run, ...(list ?? [])])
    setRunId(run.id)
    setSummary(run)
    setBreakType(undefined)
    setCreating(false)
  }

  return (
    <div className="app">
      <header className="masthead">
        <div>
          <h1>ReconX</h1>
          <p>Bank statement against ledger: every payment matched or explained.</p>
        </div>
        <div className="masthead__controls">
          {runs && runs.length > 0 && (
            <select aria-label="Reconciliation run" value={runId ?? ''} onChange={(event) => setRunId(Number(event.target.value))}>
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {runLabel(run)}
                </option>
              ))}
            </select>
          )}
          <button type="button" className="button" onClick={() => setCreating(true)}>
            New reconciliation
          </button>
        </div>
      </header>

      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {creating && <NewRunForm api={api} onCreated={created} onCancel={() => setCreating(false)} />}
      {runs && runs.length === 0 && !creating && (
        <p className="empty">No reconciliations yet. Upload a bank statement and a ledger to start one.</p>
      )}

      {summary && (
        <main className="dashboard">
          <SummaryTiles summary={summary} />
          <div className="charts">
            <Breakdown<BreakType>
              title="Open breaks by type"
              items={summary.breaks_by_type.map((row) => ({
                key: row.type,
                label: BREAK_LABELS[row.type],
                value: row.open,
                detail: `${formatMoney(row.open_amount)} · ${formatCount(row.resolved)} resolved`,
              }))}
              selected={breakType}
              onSelect={setBreakType}
            />
            <Breakdown<Rule>
              title="Matches by rule"
              items={(Object.keys(RULE_LABELS) as Rule[]).map((rule) => ({
                key: rule,
                label: RULE_LABELS[rule],
                value: summary.matches_by_rule[rule],
              }))}
            />
          </div>
          <ExceptionQueue
            api={api}
            runId={summary.id}
            type={breakType}
            onTypeChange={setBreakType}
            onResolved={() => setRefresh((value) => value + 1)}
          />
        </main>
      )}
    </div>
  )
}
