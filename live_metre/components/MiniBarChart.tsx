interface Bar {
  id: string
  name: string
  color: string
  value: number
  label: string // formatted value shown at the end of the row
}

interface MiniBarChartProps {
  title: string
  bars: Bar[]
}

export default function MiniBarChart({ title, bars }: MiniBarChartProps) {
  const max = Math.max(1, ...bars.map((bar) => bar.value))

  return (
    <div className="rounded-xl border-[0.5px] border-slate-200 bg-white px-6 py-5">
      <h3 className="text-base text-slate-500">{title}</h3>
      <div className="mt-4 space-y-4">
        {bars.map((bar) => (
          <div key={bar.id} className="flex items-center gap-3">
            <div className="w-16 truncate text-base font-medium">{bar.name}</div>
            <div className="relative h-5 flex-1 overflow-hidden rounded bg-slate-50">
              {[25, 50, 75].map((pct) => (
                <div
                  key={pct}
                  className="absolute inset-y-0 border-l-[0.5px] border-slate-200"
                  style={{ left: `${pct}%` }}
                />
              ))}
              <div
                className="absolute inset-y-0 left-0 rounded transition-[width] duration-700 ease-in-out"
                style={{ width: `${(bar.value / max) * 100}%`, backgroundColor: bar.color }}
              />
            </div>
            <div className="w-20 text-right text-lg font-medium tabular-nums">{bar.label}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
