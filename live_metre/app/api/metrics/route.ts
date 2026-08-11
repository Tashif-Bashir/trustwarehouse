import { NextResponse } from 'next/server'
import { BOARDS } from '@/lib/config'
import { getMetrics } from '@/lib/provider'
import { isMorningQueryWindow } from '@/lib/provider/bronze'

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams
  const board = params.get('board') ?? 'telesales'
  // Doors-open morning payload: real Europe/London morning window, or the
  // wallboard's own ?doors=1 demo forwarding ?morning=1 so the takeover has
  // something to show outside the window. Never true on an ordinary poll.
  const morning = isMorningQueryWindow() || params.has('morning')
  const metrics = await getMetrics(board in BOARDS ? board : 'telesales', { morning })
  return NextResponse.json(metrics, {
    headers: { 'cache-control': 'no-store' },
  })
}
