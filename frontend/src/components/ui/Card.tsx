import './ui.scss'
export default function Card({
  children,
  className = '',
  ...props
}: React.ComponentProps<'section'>) {
  return (
    <section className={`card ${className}`} {...props}>
      {children}
    </section>
  )
}
