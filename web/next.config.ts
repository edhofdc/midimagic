import type { NextConfig } from "next";

/**
 * Cache policy.
 *
 * Next.js serves prerendered pages with `Cache-Control: s-maxage=31536000` — a
 * YEAR in shared caches — while the JS chunks are content-hashed and change on
 * every build. A browser or proxy holding that year-old HTML then asks for chunk
 * filenames that no longer exist, hydration dies, and the app renders as an
 * unstyled mess seconds after a deploy looked fine. That is exactly what happened
 * here: the app was good, then a rebuild left the cached shell pointing at dead
 * chunks.
 *
 * Dangerous combination, so split the policy:
 *   - documents: always revalidate, never serve a stale shell
 *   - /_next/static/**: immutable is CORRECT here, the filenames carry a hash
 *   - API responses are proxied to the backend, which sets its own no-store
 */
const noStore = "no-cache, no-store, must-revalidate";

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        // the HTML shell must never outlive the build that produced it
        source: "/",
        headers: [{ key: "Cache-Control", value: noStore }],
      },
      {
        source: "/share/:slug",
        headers: [{ key: "Cache-Control", value: noStore }],
      },
      {
        source: "/:path((?!_next/).*)",
        headers: [{ key: "Cache-Control", value: noStore }],
      },
      {
        // hashed filenames — safe and worth caching hard
        source: "/_next/static/:path*",
        headers: [{ key: "Cache-Control", value: "public, max-age=31536000, immutable" }],
      },
    ];
  },
};

export default nextConfig;
