const apiOrigin = (process.env.API_ORIGIN || 'http://127.0.0.1:8000').replace(/\/$/, '')

/** @type {import('next').NextConfig} */
const config = {
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${apiOrigin}/:path*` }]
  },
}

export default config
