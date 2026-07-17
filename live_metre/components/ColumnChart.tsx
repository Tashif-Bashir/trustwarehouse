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
}

// Round up to a "nice" axis step (1 / 2 / 2.5 / 5 × 10^n).
function niceStep(rough: number): number {
  const power = Math.pow(10, Math.floor(Math.log10(Math.max(rough, 1))))
  const unit = rough / power
  const nice = unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 2.5 ? 2.5 : unit <= 5 ? 5 : 10
  return nice * power
}

const INTERVALS = 4 // gridlines at 0, 25, 50, 75, 100% of the axis max

export default function ColumnChart({ title, columns }: ColumnChartProps) {
  const rawMax = Math.max(1, ...columns.map((c) => c.value))
  const step = niceStep(rawMax / INTERVALS)
  const axisMax = step * INTERVALS
  const ticks = Array.from({ length: INTERVALS + 1 }, (_, i) => step * (INTERVALS - i))

  return (
    <div>
      <h3 className="text-2xl font-semibold">{title}</h3>
      <div className="mt-5 flex gap-3">
        {/* y axis labels */}
        <div className="flex h-64 flex-col justify-between text-right text-sm tabular-nums text-neutral-500">
          {ticks.map((tick) => (
            <span key={tick} className="-translate-y-1/2 leading-none first:translate-y-0 last:translate-y-0">
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
                className="absolute inset-x-0 border-t-[0.5px] border-white/10"
                style={{ top: `${(i / INTERVALS) * 100}%` }}
              />
            ))}
            <div className="absolute inset-0 flex items-end justify-around gap-4 px-2">
              {columns.map((col) => (
                <div key={col.id} className="flex h-full w-16 flex-col items-center justify-end">
                  {col.label !== undefined && (
                    <span className="mb-1.5 text-sm tabular-nums text-neutral-400">
                      {col.label}
                    </span>
                  )}
                  <div
                    className="w-full max-w-[52px] rounded-t-md transition-[height] duration-700 ease-in-out"
                    style={{
                      height: `${(col.value / axisMax) * 100}%`,
                      backgroundColor: col.color,
                    }}
                  />
                </div>
              ))}
            </div>
          </div>
          {/* agent names under the columns */}
          <div className="flex items-start justify-around gap-4 px-2 pt-2">
            {columns.map((col) => (
              <span key={col.id} className="w-16 text-center text-lg font-medium text-neutral-200">
                {col.name}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
