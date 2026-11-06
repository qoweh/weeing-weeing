const apiOrigin = (process.env.API_ORIGIN || "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);
const dev = process.env.NODE_ENV !== "production";

// 글꼴·이미지·API가 모두 같은 서버에서 오므로 'self' 중심으로 제한한다.
// Next가 인라인 부트스트랩 스크립트를 넣어 script-src에 'unsafe-inline'이 필요하고,
// 개발 서버(React Refresh)는 'unsafe-eval'도 쓴다.
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' https://raw.githubusercontent.com${dev ? " ws: wss:" : ""}`,
  "frame-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  // 화면에 문제가 없는지 확인한 뒤 Content-Security-Policy로 바꾼다.
  { key: "Content-Security-Policy-Report-Only", value: contentSecurityPolicy },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=()",
  },
];

/** @type {import('next').NextConfig} */
const config = {
  poweredByHeader: false,
  env: { NEXT_PUBLIC_API_ORIGIN: new URL(apiOrigin).origin },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/:path*` }];
  },
};

export default config;
