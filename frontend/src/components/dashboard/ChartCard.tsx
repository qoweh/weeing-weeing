import Card from '../ui/Card'
export default function ChartCard({
  title,
  description,
  children,
  className = '',
}: {
  title: string
  description?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <Card className={`chart-card ${className}`}>
      <div className="card-heading">
        <div>
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
        <span className="card-heading__sample">예시</span>
      </div>
      {children}
    </Card>
  )
}
