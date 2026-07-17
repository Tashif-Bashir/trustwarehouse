'use client'

import { useEffect, useRef, useState } from 'react'

// Animate numeric changes: whenever `target` moves, tick the displayed value
// from the previous number to the new one. Scoreboard numbers should roll,
// not jump.
export function useCountUp(target: number, durationMs = 700): number {
  const [display, setDisplay] = useState(target)
  const fromRef = useRef(target)

  useEffect(() => {
    const from = fromRef.current
    if (from === target) return
    const start = performance.now()
    let raf: number

    const step = (now: number) => {
      const progress = Math.min(1, (now - start) / durationMs)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplay(Math.round(from + (target - from) * eased))
      if (progress < 1) {
        raf = requestAnimationFrame(step)
      } else {
        fromRef.current = target
      }
    }

    raf = requestAnimationFrame(step)
    return () => {
      cancelAnimationFrame(raf)
      fromRef.current = target
    }
  }, [target, durationMs])

  return display
}
