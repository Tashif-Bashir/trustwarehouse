import type { MetadataRoute } from 'next'

// Belt to the X-Robots-Tag braces: crawlers that check robots.txt first
// never fetch the pages at all.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: '*', disallow: '/' },
  }
}
