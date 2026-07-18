import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Emit a minimal self-contained server (.next/standalone) for the Docker image
  // (Session 14.3). Vercel ignores this and builds its own way.
  output: "standalone",
  webpack: (config) => {
    // @wagmi/connectors imports optional wallet SDKs (porto, etc.) we don't use.
    // Alias them to false so the bundle doesn't try to resolve them.
    config.resolve.alias = {
      ...config.resolve.alias,
      "porto/internal": false,
      porto: false,
      accounts: false,
      "@base-org/account": false,
      "@coinbase/wallet-sdk": false,
      "@metamask/connect-evm": false,
      "@metamask/sdk": false,
      "@safe-global/safe-apps-sdk": false,
      "@safe-global/safe-apps-provider": false,
      "@walletconnect/ethereum-provider": false,
    };
    return config;
  },
  // Security headers are set in middleware.ts so they apply uniformly to static,
  // dynamic, and cached responses (next.config headers() drops CSP/HSTS on
  // full-route-cache hits).
};

export default nextConfig;
