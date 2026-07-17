import type { Metrics } from '../types'
import { getMockMetrics } from './mock'

// The single seam for swapping the data source. The UI and the API route
// only ever call getMetrics(); to go live, add a provider module (e.g.
// bronze.ts querying bronze.ascend_calls + app.bookings) and switch on
// DATA_SOURCE below. Nothing above this module changes.
export async function getMetrics(): Promise<Metrics> {
  switch (process.env.DATA_SOURCE) {
    // case 'bronze': return getBronzeMetrics()
    default:
      return getMockMetrics()
  }
}
