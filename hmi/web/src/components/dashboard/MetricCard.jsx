import Card from '../ui/Card.jsx'
import Badge from '../ui/Badge.jsx'
export default function MetricCard({ title, value, unit, note, tone, icon }) {
  return <Card className="metric"><div className="metric__heading"><h2>{title}</h2><span className="metric__icon" aria-hidden="true">{icon}</span></div><div className="metric__value">{value}<span>{unit}</span></div><Badge tone={tone}>{note}</Badge></Card>
}
