import type { Metrics } from '../types'
import { getBronzeMetrics } from './bronze'
import { getMockMetrics } from './mock'

// The single seam for swapping the data source. The UI and the API route
// only ever call getMetrics(); set DATA_SOURCE=bronze (Vercel env) for the
// real feed, anything else falls back to the drifting mock.
export async function getMetrics(): Promise<Metrics> {
  switch (process.env.DATA_SOURCE) {
    case 'bronze':
      return getBronzeMetrics()
    default:
      return getMockMetrics()
  }
}
