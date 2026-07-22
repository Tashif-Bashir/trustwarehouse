import { NextResponse } from 'next/server'
import { BOARDS } from '@/lib/config'
import { getMetrics } from '@/lib/provider'

export const dynamic = 'force-dynamic'

export async function GET(request: Request) {
  const board = new URL(request.url).searchParams.get('board') ?? 'telesales'
  const metrics = await getMetrics(board in BOARDS ? board : 'telesales')
  return NextResponse.json(metrics, {
    headers: { 'cache-control': 'no-store' },
  })
}
