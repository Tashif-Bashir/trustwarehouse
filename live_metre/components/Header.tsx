interface HeaderProps {
  title?: string
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

export default function Header({ title = 'Live telesales metre', source, secondsAgo, stale }: HeaderProps) {
  return (
    <header className="flex items-start justify-between gap-4">
      <div>
        <h1 className="font-display text-5xl font-semibold uppercase tracking-wide">
          {title}
        </h1>
        <p className="mt-1.5 text-lg text-neutral-400">
          {source} · today · {refreshedLabel(secondsAgo)}
        </p>
      </div>
      {stale ? (
        <span className="flex items-center gap-2.5 rounded-full border-[0.5px] border-amber-400/30 bg-surface px-5 py-2 font-display text-xl font-medium uppercase tracking-wider text-amber-400">
          <span className="h-3 w-3 rounded-full bg-amber-400" />
          Stale
        </span>
      ) : (
        <span className="flex items-center gap-2.5 rounded-full border-[0.5px] border-green-500/30 bg-surface px-5 py-2 font-display text-xl font-medium uppercase tracking-wider text-green-500">
          <span
            className="pulse-dot h-3 w-3 rounded-full bg-green-500"
            style={{ boxShadow: '0 0 10px rgba(34, 197, 94, 0.8)' }}
          />
          Live
        </span>
      )}
    </header>
  )
}
