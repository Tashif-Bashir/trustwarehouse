import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Live telesales metre',
  description: 'Trust Electric Heating — live telesales wallboard',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-GB">
      <body className="min-h-screen bg-[#fafafa] font-sans text-slate-900 antialiased">
        {children}
      </body>
    </html>
  )
}
