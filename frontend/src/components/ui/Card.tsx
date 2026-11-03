import type { ComponentPropsWithoutRef } from 'react'
import './ui.scss'

export default function Card({
  children,
  className = '',
  ...props
}: ComponentPropsWithoutRef<'section'>) {
  return (
    <section className={`card ${className}`} {...props}>
      {children}
    </section>
  )
}
