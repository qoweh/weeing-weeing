import './ui.scss'
export default function Button({
  children,
  variant = 'outline',
  iconOnly = false,
  className = '',
  ...props
}: React.ComponentProps<'button'> & { variant?: string; iconOnly?: boolean }) {
  return (
    <button
      className={`button button--${variant} ${iconOnly ? 'button--icon' : ''} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}
