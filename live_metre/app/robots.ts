import type { MetadataRoute } from 'next'

// ALLOW crawling on purpose: Google must be able to fetch a page to see the
// X-Robots-Tag noindex header. A robots.txt Disallow blocks the crawl, so
// Google never re-reads the page and keeps serving its stale indexed copy
// (bit us Aug 2026 — a June cache of the dashboard survived Disallow+noindex).
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: '*', allow: '/' },
  }
}
