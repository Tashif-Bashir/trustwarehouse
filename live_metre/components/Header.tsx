interface HeaderProps {
  source: string
  secondsAgo: number | null // null = nothing fetched yet
  stale: boolean
}

function refreshedLabel(secondsAgo: number | null): string {
  if (secondsAgo === null) return 'connecting…'
  if (secondsAgo < 2) return 'refreshed just now'
  if (secondsAgo < 120) return `refreshed ${secondsAgo}s ago`
  return `refreshed ${Math.floor(secondsAgo / 60)}m ago`
}

export default function Header({ source, secondsAgo, stale }: HeaderProps) {
  return (
    <header className="flex items-start justify-between gap-4">
      <div>
        <h1 className="text-4xl font-semibold tracking-tight">Live telesales metre</h1>
        <p className="mt-1 text-lg text-neutral-400">
          {source} · today · {refreshedLabel(secondsAgo)}
        </p>
      </div>
      {stale ? (
        <span className="flex items-center gap-2.5 rounded-full bg-neutral-900 px-5 py-2 text-lg font-medium text-amber-400">
          <span className="h-3 w-3 rounded-full bg-amber-400" />
          Stale
        </span>
      ) : (
        <span className="flex items-center gap-2.5 rounded-full bg-neutral-900 px-5 py-2 text-lg font-medium text-green-500">
          <span className="pulse-dot h-3 w-3 rounded-full bg-green-500" />
          Live
        </span>
      )}
    </header>
  )
}
