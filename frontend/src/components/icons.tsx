/**
 * Inline SVG icon set (Phosphor-derived geometry, 24×24 grid, 1.75px stroke).
 * Unicode glyphs are not icons: they inherit font metrics, shift across
 * platforms, and are read aloud by screen readers. These are drawn, sized in
 * `em`, and marked decorative — status is always carried by adjacent text too.
 */
interface IconProps {
  size?: number | string;
  className?: string;
}

function svgProps(size: number | string, className?: string) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    focusable: false,
    className,
  };
}

/* ── Status ── */
export function IconCheck({ size = "1em", className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

export function IconWarning({ size = "1em", className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <path d="M12 3.6 2.6 19.4h18.8L12 3.6Z" />
      <path d="M12 9.6v4.2" />
      <path d="M12 16.9h.01" />
    </svg>
  );
}

export function IconWarningCircle({ size = "1em", className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5" />
      <path d="M12 16h.01" />
    </svg>
  );
}

export function IconXCircle({ size = "1em", className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <circle cx="12" cy="12" r="9" />
      <path d="m15 9-6 6M9 9l6 6" />
    </svg>
  );
}

export function IconClock({ size = "1em", className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
  );
}

/* ── Navigation ── */
export function IconGauge({ size = "1em", className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <path d="M4 18a8 8 0 1 1 16 0" />
      <path d="m12 14 4-4" />
      <circle cx="12" cy="18" r="1.4" />
    </svg>
  );
}

export function IconCube({ size = "1em", className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <path d="M12 2.8 20.5 7v10L12 21.2 3.5 17V7L12 2.8Z" />
      <path d="M12 21.2V12M12 12 3.5 7M12 12l8.5-5" />
    </svg>
  );
}

export function IconChart({ size = "1em", className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <path d="M4 4v16h16" />
      <path d="m7.5 14 3.5-4 3 2.5L19 7" />
    </svg>
  );
}

export function IconList({ size = "1em", className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <path d="M8 6h12M8 12h12M8 18h12" />
      <path d="M4 6h.01M4 12h.01M4 18h.01" />
    </svg>
  );
}

export function IconSettings({ size = "1em", className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <circle cx="12" cy="12" r="3.2" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.11a1.7 1.7 0 0 0-1.1-1.56 1.7 1.7 0 0 0-1.88.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.11A1.7 1.7 0 0 0 4.67 8.9a1.7 1.7 0 0 0-.34-1.88l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6h.08A1.7 1.7 0 0 0 10.11 3V3a2 2 0 1 1 4 0v.11a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87V9a1.7 1.7 0 0 0 1.56 1.03H21a2 2 0 1 1 0 4h-.11A1.7 1.7 0 0 0 19.4 15Z" />
    </svg>
  );
}

/* ── Theme ── */
export function IconSun({ size = "1em", className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4" />
    </svg>
  );
}

export function IconMoon({ size = "1em", className }: IconProps) {
  return (
    <svg {...svgProps(size, className)}>
      <path d="M20 14.2A8.2 8.2 0 0 1 9.8 4a8.4 8.4 0 1 0 10.2 10.2Z" />
    </svg>
  );
}

/* Level → icon, so risk is never carried by color alone. */
export const LEVEL_ICON = {
  normal: IconCheck,
  level1_caution: IconWarning,
  level2_warning: IconWarningCircle,
  level3_critical: IconXCircle,
} as const;
