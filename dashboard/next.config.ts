import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: false,
  allowedDevOrigins: ['192.168.1.200'], // <--- BU SATIRI EKLEYİN
};

export default nextConfig;
