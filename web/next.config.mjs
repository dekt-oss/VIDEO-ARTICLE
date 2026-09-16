/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // ★ 이미지 최적화 끄기 (2026-09-16). 이 앱은 next/image 를 한 곳도 쓰지 않는다.
  //
  //   왜 필요한가: GHSA-2xp9-vwfh-vxw4 는 `/_next/image` 의 **미인증 RCE** 였다.
  //   middleware 로 막으려 했는데 **Vercel 에서는 안 먹는다** — 실측:
  //     `/_next/image?url=...` → 400 `X-Vercel-Error: INVALID_IMAGE_OPTIMIZE_REQUEST`
  //   즉 이 경로는 Vercel 플랫폼의 이미지 최적화기가 **Next 미들웨어보다 앞에서** 처리한다.
  //   (로컬 `next start` 는 미들웨어가 잡아서 307 이 나온다 — 그래서 로컬만 보면 속는다.)
  //
  //   `unoptimized: true` 는 빌드 산출물에 "최적화 안 씀"을 선언해 Vercel 이 그 경로를
  //   아예 만들지 않게 한다. 안 쓰는 실행 표면을 없애는 쪽이 막는 것보다 확실하다.
  //   middleware 의 matcher 예외 제거도 그대로 둔다(로컬·자체호스팅에서 유효).
  images: { unoptimized: true },
};

export default nextConfig;
