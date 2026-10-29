import type { ApiErrorBody, Break, BreakStatus, BreakType, Page, Run, RunSummary, Side, Upload } from './types'

// The API is served under /api: Vite proxies it in development, nginx in the Compose stack.
const BASE = '/api'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly errors: string[]

  constructor(status: number, body: Partial<ApiErrorBody>) {
    super(body.detail ?? `Request failed with status ${status}`)
    this.status = status
    this.code = body.code ?? 'unknown'
    this.errors = body.errors ?? []
  }
}

export interface BreakQuery {
  type?: BreakType
  status?: BreakStatus
  limit: number
  offset: number
}

export interface Api {
  listRuns(): Promise<Run[]>
  getRun(id: number): Promise<RunSummary>
  listBreaks(runId: number, query: BreakQuery): Promise<Page<Break>>
  resolveBreak(id: number, note: string): Promise<Break>
  upload(kind: Side, file: File): Promise<Upload>
  startRun(bankUploadId: number, ledgerUploadId: number, dateWindowDays: number): Promise<RunSummary>
}

async function errorBody(response: Response): Promise<Partial<ApiErrorBody>> {
  try {
    const body: unknown = await response.json()
    if (body && typeof body === 'object' && typeof (body as ApiErrorBody).detail === 'string') {
      return body as ApiErrorBody
    }
  } catch {
    // Not JSON (a proxy error page, say): fall back to the status code alone.
  }
  return {}
}

export function createApi(fetcher: typeof fetch = fetch): Api {
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetcher(`${BASE}${path}`, init)
    if (!response.ok) {
      throw new ApiError(response.status, await errorBody(response))
    }
    return (await response.json()) as T
  }

  function json(method: string, body: unknown): RequestInit {
    return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
  }

  return {
    listRuns: () => request<Run[]>('/runs'),
    getRun: (id) => request<RunSummary>(`/runs/${id}`),
    listBreaks: (runId, query) => {
      const params = new URLSearchParams({ limit: String(query.limit), offset: String(query.offset) })
      if (query.type) params.set('type', query.type)
      if (query.status) params.set('status', query.status)
      return request<Page<Break>>(`/runs/${runId}/breaks?${params}`)
    },
    resolveBreak: (id, note) => request<Break>(`/breaks/${id}/resolve`, json('POST', { note })),
    upload: (kind, file) => {
      const form = new FormData()
      form.append('file', file)
      return request<Upload>(`/uploads/${kind}`, { method: 'POST', body: form })
    },
    startRun: (bankUploadId, ledgerUploadId, dateWindowDays) =>
      request<RunSummary>(
        '/runs',
        json('POST', {
          bank_upload_id: bankUploadId,
          ledger_upload_id: ledgerUploadId,
          date_window_days: dateWindowDays,
        }),
      ),
  }
}
