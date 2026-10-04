export function LogoMark({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="logo-mark">
      <rect width="32" height="32" className="logo-mark-bg" />
      <rect x="8" y="7" width="5" height="18" className="logo-mark-k" />
      <polygon points="12.5,16.5 19.5,7 25.5,7 16.5,19" className="logo-mark-k" />
      <polygon points="16.5,14 25.5,25 19.5,25 12.5,17" className="logo-mark-k" />
    </svg>
  );
}

export function Logo() {
  return (
    <span className="logo">
      <LogoMark />
      <span className="logo-text">Supply Chain Planner</span>
    </span>
  );
}
