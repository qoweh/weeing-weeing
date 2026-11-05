import '../styles/tailwind.css'
import '../styles/index.scss'

export const metadata = {
  title: '위잉위잉 · Equipment AI',
  description: '설비 정비 지원 대시보드',
  icons: { icon: '/assets/IMAGE/weeing-favicon.svg' },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  )
}
