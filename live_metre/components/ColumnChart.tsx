import Avatar from '@/components/Avatar'

interface Column {
  id: string
  name: string
  color: string
  value: number
  label?: string // optional value label shown above the column
}

interface ColumnChartProps {
  title: string
  columns: Column[]
  delayMs?: number
}

// Round up to a "nice" axis step (1 / 2 / 2.5 / 5 × 10^n).
function niceStep(rough: number): number {
  const power = Math.pow(10, Math.floor(Math.log10(Math.max(rough, 1))))
  const unit = rough / power
  const nice = unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 2.5 ? 2.5 : unit <= 5 ? 5 : 10
  return nice * power
}

const INTERVALS = 4 // gridlines at 0, 25, 50, 75, 100% of the axis max

export default function ColumnChart({ title, columns, delayMs = 0 }: ColumnChartProps) {
  const rawMax = Math.max(1, ...columns.map((c) => c.value))
  const step = niceStep(rawMax / INTERVALS)
  const axisMax = step * INTERVALS
  const ticks = Array.from({ length: INTERVALS + 1 }, (_, i) => step * (INTERVALS - i))

  return (
    <div className="fade-up" style={{ animationDelay: `${delayMs}ms` }}>
      <h3 className="font-display text-3xl font-semibold uppercase tracking-wide">{title}</h3>
      <div className="mt-6 flex gap-3">
        {/* y axis labels */}
        <div className="flex h-64 flex-col justify-between text-right font-display text-base font-medium tabular-nums text-neutral-500">
          {ticks.map((tick) => (
            <span
              key={tick}
              className="-translate-y-1/2 leading-none first:translate-y-0 last:translate-y-0"
            >
              {Number.isInteger(tick) ? tick : tick.toFixed(1)}
            </span>
          ))}
        </div>
        <div className="flex-1">
          {/* plot area with recessive gridlines */}
          <div className="relative h-64">
            {ticks.map((tick, i) => (
              <div
                key={tick}
                className="absolute inset-x-0 border-t-[0.5px] border-white/[0.07]"
                style={{ top: `${(i / INTERVALS) * 100}%` }}
              />
            ))}
            <div className="absolute inset-0 flex items-end justify-around gap-4 px-2">
              {columns.map((col) => (
                <div key={col.id} className="flex h-full w-16 flex-col items-center justify-end">
                  {col.label !== undefined && (
                    <span className="mb-2 font-display text-lg font-medium tabular-nums text-neutral-300">
                      {col.label}
                    </span>
                  )}
                  <div
                    className="w-full max-w-[52px] rounded-t-md transition-[height] duration-700 ease-in-out"
                    style={{
                      height: `${(col.value / axisMax) * 100}%`,
                      backgroundColor: col.color,
                      boxShadow: `0 0 14px color-mix(in srgb, ${col.color} 18%, transparent)`,
                    }}
                  />
                </div>
              ))}
            </div>
          </div>
          {/* agent avatars + names under the columns */}
          <div className="flex items-start justify-around gap-4 px-2 pt-2.5">
            {columns.map((col) => (
              <span key={col.id} className="flex w-16 flex-col items-center gap-1">
                <Avatar id={col.id} name={col.name} color={col.color} size={28} />
                <span className="text-center font-display text-lg font-medium text-neutral-200">
                  {col.name}
                </span>
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
