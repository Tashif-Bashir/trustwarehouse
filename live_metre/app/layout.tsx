import type { Metadata } from 'next'
import { Barlow, Barlow_Condensed } from 'next/font/google'
import { AGENTS } from '@/lib/config'
import './globals.css'

// Scoreboard typography: Barlow Condensed for the big numerals (athletic,
// reads from across a room), Barlow as its natural body companion.
const barlow = Barlow({
  subsets: ['latin'],
  weight: ['400', '500'],
  variable: '--font-body',
})

const barlowCondensed = Barlow_Condensed({
  subsets: ['latin'],
  weight: ['500', '600'],
  variable: '--font-display',
})

export const metadata: Metadata = {
  title: 'Live telesales metre',
  description: 'Trust Electric Heating — live telesales wallboard',
}

// The team stripe: one hard colour stop per agent, roster order. The page's
// signature mark — ties the whole board to the four agent colours.
const stripe = `linear-gradient(90deg, ${AGENTS.map(
  (a, i) => `${a.color} ${(i / AGENTS.length) * 100}% ${((i + 1) / AGENTS.length) * 100}%`
).join(', ')})`

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-GB">
      <body
        className={`${barlow.variable} ${barlowCondensed.variable} vignette noise min-h-screen font-body text-neutral-50 antialiased`}
      >
        <div aria-hidden className="fixed inset-x-0 top-0 z-50 h-[3px]" style={{ background: stripe }} />
        {children}
      </body>
    </html>
  )
}
