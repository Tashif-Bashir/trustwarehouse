import type { Metrics } from '../types'
import { getBronzeMetrics } from './bronze'
import { getMockMetrics } from './mock'

export interface MetricsOptions {
  // Doors-open morning takeover: true when the request lands in the real
  // Europe/London morning window or carries ?morning/?doors (see route.ts).
  // Gates the one genuinely new BigQuery query arm (fresh leads overnight).
  morning?: boolean
}

// The single seam for swapping the data source. The UI and the API route
// only ever call getMetrics(boardId); set DATA_SOURCE=bronze (Vercel env)
// for the real feed, anything else falls back to the drifting mock.
export async function getMetrics(
  boardId: string = 'telesales',
  opts: MetricsOptions = {}
): Promise<Metrics> {
  switch (process.env.DATA_SOURCE) {
    case 'bronze':
      return getBronzeMetrics(boardId, opts)
    default:
      return getMockMetrics(boardId, opts)
  }
}
