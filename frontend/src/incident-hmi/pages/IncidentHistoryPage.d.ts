import type { ComponentType } from 'react'

declare const IncidentHistoryPage: ComponentType<{
  user: { name: string; role: string; employee_no: string }
  busy: boolean
  onBusyChange: (busy: boolean) => void
  onSessionExpired: () => void
  onOpenDraft: (incidentId: string, analysis: unknown) => void
  onOpenReport: (
    reportId: string,
    incidentId: string | null,
    version?: number,
  ) => void
  focus: { id: string; key: number } | null
  onFocusHandled: (key: number) => void
}>
export default IncidentHistoryPage
