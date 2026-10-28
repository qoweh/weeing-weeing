import Card from '../ui/Card.jsx'
export default function ChartCard({ title, description, children, className = '' }) {
  return <Card className={`chart-card ${className}`}><div className="card-heading"><div><h2>{title}</h2>{description && <p>{description}</p>}</div><span className="card-heading__sample">예시</span></div>{children}</Card>
}
