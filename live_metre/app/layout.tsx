import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Live telesales metre',
  description: 'Trust Electric Heating — live telesales wallboard',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-GB">
      <body className="min-h-screen bg-black font-sans text-neutral-50 antialiased">
        {children}
      </body>
    </html>
  )
}
