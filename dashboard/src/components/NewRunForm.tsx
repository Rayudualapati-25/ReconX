import { useState } from 'react'

import type { Api } from '../api'
import { ApiError } from '../api'
import type { RunSummary } from '../types'

interface Props {
  api: Api
  onCreated: (run: RunSummary) => void
  onCancel: () => void
}

interface Failure {
  message: string
  details: string[]
}

export function NewRunForm({ api, onCreated, onCancel }: Props) {
  const [bankFile, setBankFile] = useState<File | null>(null)
  const [ledgerFile, setLedgerFile] = useState<File | null>(null)
  const [windowDays, setWindowDays] = useState(3)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<Failure | null>(null)

  const submit = async () => {
    if (!bankFile || !ledgerFile) return
    setBusy(true)
    setFailure(null)
    try {
      const bank = await api.upload('bank', bankFile).catch(prefix('Bank statement'))
      const ledger = await api.upload('ledger', ledgerFile).catch(prefix('Ledger'))
      onCreated(await api.startRun(bank.id, ledger.id, windowDays))
    } catch (caught) {
      setFailure({
        message: caught instanceof Error ? caught.message : 'Something went wrong.',
        details: caught instanceof ApiError ? caught.errors : [],
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      className="panel new-run"
      aria-label="New reconciliation"
      onSubmit={(event) => {
        event.preventDefault()
        void submit()
      }}
    >
      <h2 className="panel__title">New reconciliation</h2>
      <p className="hint">
        CSV files with a date, an amount (or debit and credit columns), and optionally a reference
        and a description. The same file uploaded twice is stored once.
      </p>
      <div className="new-run__fields">
        <label>
          Bank statement
          <input type="file" accept=".csv,text/csv" onChange={(event) => setBankFile(event.target.files?.[0] ?? null)} />
        </label>
        <label>
          Ledger
          <input type="file" accept=".csv,text/csv" onChange={(event) => setLedgerFile(event.target.files?.[0] ?? null)} />
        </label>
        <label>
          Date window (days)
          <input
            type="number"
            min={0}
            max={30}
            value={windowDays}
            onChange={(event) => setWindowDays(Number(event.target.value))}
          />
        </label>
      </div>
      {failure && (
        <div className="alert" role="alert">
          <p>{failure.message}</p>
          {failure.details.length > 0 && (
            <ul>
              {failure.details.map((detail) => (
                <li key={detail}>{detail}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="actions">
        <button type="submit" className="button" disabled={busy || !bankFile || !ledgerFile}>
          {busy ? 'Reconciling…' : 'Reconcile'}
        </button>
        <button type="button" className="button button--quiet" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

// Name the file in an upload error, so "row 3: amount 'ten' is not a number" has a context.
function prefix(file: string) {
  return (error: unknown): never => {
    if (error instanceof ApiError) {
      throw new ApiError(error.status, { detail: `${file}: ${error.message}`, code: error.code, errors: error.errors })
    }
    throw error
  }
}
