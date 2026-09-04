import type { NextConfig } from "next";

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8080";

const nextConfig: NextConfig = {
  // Self-contained server for the container image (infrastructure/docker/frontend.Dockerfile).
  output: "standalone",
  // The browser only talks to this origin; /api/* is proxied to the Spring backend.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
