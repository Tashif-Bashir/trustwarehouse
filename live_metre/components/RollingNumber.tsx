'use client'

import { useEffect, useRef, useState } from 'react'

const DIGITS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']

// Height of one digit cell, in em of the inherited font size. Slightly over 1em
// so tall numerals never clip against the top/bottom of the window.
const CELL_EM = 1.16
const ROLL_MS = 900
const STAGGER_MS = 70 // each column to the LEFT starts this much later

/**
 * Mechanical odometer-style number.
 *
 * Every digit is a 0-9 strip inside an overflow-hidden window; changing the
 * value translates each strip to its target digit, so the numerals physically
 * roll. Units column leads and each column to its left follows on a stagger —
 * the cascade a real counter makes when it ticks over.
 *
 * Columns take their width from the widest glyph in their own 0-9 strip, so the
 * layout never shifts as digits change (no dependence on `ch` sizing).
 *
 * `onIncrease` fires only when the value goes UP (never on first paint) — this
 * is the hook point for a money sound.
 */
export default function RollingNumber({
  value,
  prefix = '',
  onIncrease,
}: {
  value: number
  prefix?: string
  onIncrease?: (delta: number) => void
}) {
  const rounded = Math.round(value)

  const prev = useRef(rounded)
  useEffect(() => {
    if (rounded > prev.current) onIncrease?.(rounded - prev.current)
    prev.current = rounded
  }, [rounded, onIncrease])

  // Roll up from zeros on first paint (keeps the old count-up reveal), while the
  // digit columns render at their final count immediately so nothing reflows.
  const [rolled, setRolled] = useState(false)
  useEffect(() => {
    const id = requestAnimationFrame(() => setRolled(true))
    return () => cancelAnimationFrame(id)
  }, [])

  const text = prefix + rounded.toLocaleString('en-GB')
  const chars = text.split('')

  // Number each digit from the right so the units column gets zero delay.
  const orderFromRight: number[] = []
  let seen = 0
  for (let i = chars.length - 1; i >= 0; i--) {
    orderFromRight[i] = /\d/.test(chars[i]) ? seen++ : -1
  }

  return (
    <span
      className="inline-flex overflow-hidden"
      style={{ height: `${CELL_EM}em` }}
      aria-label={text}
    >
      {chars.map((ch, i) => {
        const cellStyle = { height: `${CELL_EM}em`, lineHeight: `${CELL_EM}em` }

        if (orderFromRight[i] < 0) {
          return (
            <span key={i} aria-hidden style={cellStyle}>
              {ch}
            </span>
          )
        }

        const target = rolled ? Number(ch) : 0
        return (
          <span
            key={i}
            aria-hidden
            className="relative inline-block overflow-hidden"
            style={cellStyle}
          >
            <span
              className="block will-change-transform"
              style={{
                transform: `translateY(-${target * CELL_EM}em)`,
                transitionProperty: 'transform',
                transitionDuration: `${ROLL_MS}ms`,
                transitionDelay: `${orderFromRight[i] * STAGGER_MS}ms`,
                // gentle settle at the end, like a wheel coming to rest
                transitionTimingFunction: 'cubic-bezier(0.22, 1, 0.28, 1)',
              }}
            >
              {DIGITS.map((d) => (
                <span key={d} className="block text-center" style={cellStyle}>
                  {d}
                </span>
              ))}
            </span>
          </span>
        )
      })}
    </span>
  )
}
