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
        <h1 className="text-3xl font-medium tracking-tight">Live telesales metre</h1>
        <p className="mt-1 text-base text-slate-500">
          Ascend outbound activity · today · {source} · {refreshedLabel(secondsAgo)}
        </p>
      </div>
      {stale ? (
        <span className="flex items-center gap-2 rounded-full border-[0.5px] border-amber-300 bg-amber-50 px-4 py-1.5 text-base font-medium text-amber-700">
          <span className="h-2.5 w-2.5 rounded-full bg-amber-500" />
          Stale
        </span>
      ) : (
        <span className="flex items-center gap-2 rounded-full border-[0.5px] border-emerald-300 bg-emerald-50 px-4 py-1.5 text-base font-medium text-emerald-700">
          <span className="pulse-dot h-2.5 w-2.5 rounded-full bg-emerald-500" />
          Live
        </span>
      )}
    </header>
  )
}
