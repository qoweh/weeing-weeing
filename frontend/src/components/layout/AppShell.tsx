import Header from './Header'
import Sidebar from './Sidebar'
import './layout.scss'
export default function AppShell({
  theme,
  onToggleTheme,
  user,
  onLogin,
  onLogout,
  children,
}: {
  theme: string
  onToggleTheme: () => void
  user: { name: string } | null
  onLogin?: () => void
  onLogout: () => void
  children: React.ReactNode
}) {
  return (
    <div className="shell">
      <Header
        user={user}
        onLogin={onLogin}
        onLogout={onLogout}
        theme={theme}
        onToggleTheme={onToggleTheme}
      />
      <Sidebar />
      <main className="shell__content" id="main-content">
        {children}
      </main>
    </div>
  )
}
