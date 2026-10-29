import './ui.scss'
export default function Button({ children, variant = 'outline', iconOnly = false, className = '', ...props }) { return <button className={`button button--${variant} ${iconOnly ? 'button--icon' : ''} ${className}`} {...props}>{children}</button> }
