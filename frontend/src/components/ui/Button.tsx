import type { ComponentPropsWithRef } from 'react'
import './ui.scss'

type ButtonProps = ComponentPropsWithRef<'button'> & {
  variant?: string
  iconOnly?: boolean
}

export default function Button({
  children,
  variant = 'outline',
  iconOnly = false,
  className = '',
  ...props
}: ButtonProps) {
  return (
    <button
      className={`button button--${variant} ${iconOnly ? 'button--icon' : ''} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}
