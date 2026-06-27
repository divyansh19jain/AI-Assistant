/** @type {import('next').NextConfig} */

// Where the Next server forwards browser /api/* calls to. In Docker/Coolify this is
// the internal backend service (http://backend:8000); native `npm run dev` falls back
// to localhost. Read at build time and baked into the standalone server's manifest.
const backendInternalUrl = process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";

const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle so the production image stays small.
  output: "standalone",
  // Same-origin API proxy: the browser calls /api/* on the frontend origin and the
  // Next server relays to the backend over the internal network. This keeps the
  // backend off the public internet and avoids baking a backend URL into the client
  // bundle. It is bypassed whenever NEXT_PUBLIC_API_BASE_URL is set to an absolute
  // URL (split-domain setup) — see frontend/lib/api.ts.
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backendInternalUrl}/api/:path*` },
    ];
  },
};

module.exports = nextConfig;
