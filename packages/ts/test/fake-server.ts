/** Local fake of the Flexen API: records every request and answers from a queue or a handler. No network. */
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http'
import type { AddressInfo } from 'node:net'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

export interface Recorded {
  method: string
  url: string
  path: string
  query: Record<string, string>
  headers: IncomingMessage['headers']
  body: string
  json: unknown
}

export interface FakeResponse {
  status?: number
  headers?: Record<string, string>
  json?: unknown
  text?: string
  /** Wait before answering (for timeout and cancel tests). */
  delayMs?: number
}

export type Handler = (req: Recorded) => FakeResponse | Promise<FakeResponse>

export const OK_HEADERS = { 'X-Request-Id': 'req_test_1', 'X-Credits-Charged': '1', 'X-Credits-Remaining': '18341' }

export function errorBody(code: string, message = `message for ${code}`, requestId = 'req_err_1'): unknown {
  return { error: { code, message, request_id: requestId } }
}

export interface Fake {
  url: string
  requests: Recorded[]
  queue(...responses: FakeResponse[]): void
  handle(h: Handler): void
  /** Forget requests, queued responses and the handler. */
  reset(): void
  close(): Promise<void>
}

export async function startFake(): Promise<Fake> {
  const requests: Recorded[] = []
  const queued: FakeResponse[] = []
  let handler: Handler | null = null
  const server = createServer((req: IncomingMessage, res: ServerResponse) => {
    const chunks: Buffer[] = []
    req.on('data', (c: Buffer) => chunks.push(c))
    req.on('end', async () => {
      const body = Buffer.concat(chunks).toString('utf8')
      const u = new URL(req.url ?? '/', 'http://fake')
      let json: unknown = null
      try {
        json = body === '' ? null : JSON.parse(body)
      } catch {
        json = undefined
      }
      const rec: Recorded = { method: req.method ?? '', url: req.url ?? '', path: u.pathname, query: Object.fromEntries(u.searchParams), headers: req.headers, body, json }
      requests.push(rec)
      const r: FakeResponse = handler ? await handler(rec) : (queued.shift() ?? { status: 500, json: { error: { code: 'internal_error', message: 'fake: nothing queued', request_id: 'req_fake' } } })
      const send = (): void => {
        if (res.destroyed) return
        const headers: Record<string, string> = { ...(r.headers ?? {}) }
        let payload = r.text ?? ''
        if (r.json !== undefined) {
          payload = JSON.stringify(r.json)
          headers['Content-Type'] = 'application/json'
        }
        res.writeHead(r.status ?? 200, headers)
        res.end(payload)
      }
      if (r.delayMs) setTimeout(send, r.delayMs)
      else send()
    })
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const { port } = server.address() as AddressInfo
  return {
    url: `http://127.0.0.1:${port}`,
    requests,
    queue: (...rs) => queued.push(...rs),
    handle: (h) => {
      handler = h
    },
    reset: () => {
      requests.length = 0
      queued.length = 0
      handler = null
    },
    close: () =>
      new Promise<void>((resolve) => {
        server.closeAllConnections()
        server.close(() => resolve())
      }),
  }
}

/** Request and response examples of the contract (contract/examples.json), per operationId. */
export const EXAMPLES = JSON.parse(readFileSync(fileURLToPath(new URL('../../../contract/examples.json', import.meta.url)), 'utf8')) as Record<
  string,
  { params: Record<string, unknown>; request: unknown; requestExamples: Record<string, unknown>; response: unknown; responseExamples: Record<string, unknown> }
>

export const TEST_KEY = 'flx_test_0123456789abcdefghijABCDEFGHIJ0123456789xyz'
