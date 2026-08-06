/** @type {import('next').NextConfig} */
const nextConfig = {
  // Internal wallboard: keep it out of search engines. This stops indexing,
  // not access — the URL still works for the wall screens and the dashboard
  // iframe, which is exactly the balance we want.
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [{ key: 'X-Robots-Tag', value: 'noindex, nofollow, noarchive' }],
      },
    ]
  },
}

export default nextConfig
