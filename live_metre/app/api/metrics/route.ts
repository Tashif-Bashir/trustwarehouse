import { NextResponse } from 'next/server'
import { getMetrics } from '@/lib/provider'

export const dynamic = 'force-dynamic'

export async function GET() {
  const metrics = await getMetrics()
  return NextResponse.json(metrics, {
    headers: { 'cache-control': 'no-store' },
  })
}
