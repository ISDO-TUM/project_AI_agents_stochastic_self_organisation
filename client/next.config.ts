import type { NextConfig } from "next";

// INTERNAL_API_URL is a server-side env var (no NEXT_PUBLIC_ prefix).
const internalApiUrl = process.env.INTERNAL_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${internalApiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
