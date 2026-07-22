import type { Metadata } from 'next'
import Wallboard from '@/components/Wallboard'

export const metadata: Metadata = {
  title: 'Live sales & ops metre',
}

export default function SalesOpsPage() {
  return <Wallboard boardId="team" />
}
