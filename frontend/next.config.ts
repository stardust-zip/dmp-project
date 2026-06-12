import type { NextConfig } from "next";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  skipTrailingSlashRedirect: true,
  async rewrites() {
    const backendUrl = process.env.BACKEND_API_URL ?? "http://localhost:8000";

    return {
      beforeFiles: [
        {
          source: "/api/backend/:path*/",
          destination: `${backendUrl}/:path*/`,
        },
        {
          source: "/api/backend/:path*",
          destination: `${backendUrl}/:path*`,
        },
      ],
    };
  },
  turbopack: {
    root: projectRoot,
  },
};

export default nextConfig;
