const fields = [
  'department',
  'processImpact',
  'actualActions',
  'actionStatus',
  'replacedParts',
  'actionAt',
  'causeCategory',
  'confirmedCause',
  'causeEvidence',
  'aiAssessment',
  'trialResult',
  'trialDetails',
  'downtimeStart',
  'downtimeEnd',
  'resolution',
  'followUp',
  'followUpOwner',
  'followUpDue',
]
const dates = new Set(['actionAt', 'downtimeStart', 'downtimeEnd'])
const snake = (name: string) =>
  name.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)

function localTime(value: string | null | undefined) {
  if (!value) return ''
  const time = new Date(value)
  const adjusted = new Date(time.getTime() - time.getTimezoneOffset() * 60_000)
  return adjusted.toISOString().slice(0, 16)
}

export function formValues(
  document: { form_data?: Record<string, string | null> } | null,
) {
  if (!document) return {}
  return Object.fromEntries(
    fields.map((name) => {
      const value = document.form_data?.[snake(name)]
      return [name, dates.has(name) ? localTime(value) : (value ?? '')]
    }),
  )
}

export function draftValues(values: Record<string, string | null | undefined>) {
  return Object.fromEntries(
    fields.map((name) => {
      let value: string | null = values[name] ?? ''
      if (dates.has(name)) value = value ? new Date(value).toISOString() : null
      return [snake(name), value]
    }),
  )
}
