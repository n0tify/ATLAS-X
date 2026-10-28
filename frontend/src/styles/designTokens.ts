/** Liquid-glass design tokens for ATLAS-X. */

export const colors = {
  // Backgrounds - Deep violet, indigo, midnight blue, near-black
  background: {
    primary: '#05070d',        // Near-black midnight
    secondary: '#0a0d17',      // Deep midnight
    tertiary: '#111522',       // Layered darkness
    surface: '#161c2e',        // Glass surface base
    elevated: '#1d243a',       // Elevated glass surface
  },

  // Accents - Restrained cyan, electric blue, violet, magenta
  accent: {
    cyan: '#00e5ff',           // Electric cyan (primary interactive)
    cyanDim: 'rgba(0, 229, 255, 0.1)',
    cyanGlow: 'rgba(0, 229, 255, 0.4)',
    blue: '#3b82f6',           // Electric blue
    blueDim: 'rgba(59, 130, 246, 0.1)',
    violet: '#8b5cf6',         // Electric violet (primary brand)
    violetDim: 'rgba(139, 92, 246, 0.1)',
    violetGlow: 'rgba(139, 92, 246, 0.4)',
    indigo: '#6366f1',         // Indigo
    indigoDim: 'rgba(99, 102, 241, 0.1)',
    magenta: '#d946ef',        // Restrained magenta
    magentaDim: 'rgba(217, 70, 239, 0.1)',
    success: '#10b981',
    successDim: 'rgba(16, 185, 129, 0.1)',
    warning: '#f59e0b',
    warningDim: 'rgba(245, 158, 11, 0.1)',
    error: '#ef4444',
    errorDim: 'rgba(239, 68, 68, 0.1)',
  },

  // Text
  text: {
    primary: '#f8fafc',       // White
    secondary: '#cbd5e1',     // Light gray
    tertiary: '#94a3b8',      // Medium gray
    muted: '#64748b',         // Dark gray
  },

  // Borders
  border: {
    primary: 'rgba(139, 92, 246, 0.25)',      // Violet-tinted
    secondary: 'rgba(99, 102, 241, 0.18)',    // Indigo-tinted
    tertiary: 'rgba(255, 255, 255, 0.08)',    // White-tinted
    highlight: 'rgba(0, 229, 255, 0.3)',      // Cyan highlight
  },

  // Glass
  glass: {
    surface: 'rgba(22, 28, 46, 0.55)',        // Dark glass
    surfaceLight: 'rgba(30, 41, 59, 0.4)',    // Lighter glass
    surfaceElevated: 'rgba(29, 36, 58, 0.7)', // Elevated glass
    border: 'rgba(139, 92, 246, 0.2)',        // Glass border
    borderHighlight: 'rgba(0, 229, 255, 0.15)', // Highlight border
    highlight: 'rgba(255, 255, 255, 0.08)',   // Specular highlight
    highlightStrong: 'rgba(255, 255, 255, 0.15)', // Strong highlight
    shadow: 'rgba(0, 0, 0, 0.4)',             // Glass shadow
    shadowStrong: 'rgba(0, 0, 0, 0.5)',       // Strong shadow
  },
} as const;

export const typography = {
  fontFamily: {
    primary: '"Times New Roman", Times, serif',  // Times New Roman as specified
    mono: '"JetBrains Mono", "Fira Code", Consolas, monospace',
  },
  fontSize: {
    xs: '0.7rem',       // 11px
    sm: '0.8rem',       // 13px
    base: '0.95rem',    // 15px
    lg: '1.05rem',      // 17px
    xl: '1.2rem',       // 19px
    '2xl': '1.5rem',    // 24px
    '3xl': '1.875rem',  // 30px
    '4xl': '2.25rem',   // 36px
    '5xl': '3rem',      // 48px
  },
  fontWeight: {
    normal: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
  },
  lineHeight: {
    tight: 1.25,
    normal: 1.55,
    relaxed: 1.75,
  },
  letterSpacing: {
    normal: 'normal',
    tight: '-0.02em',
    wide: '0.05em',
    wider: '0.1em',
  },
} as const;

export const spacing = {
  0: '0',
  1: '0.25rem',   // 4px
  2: '0.5rem',    // 8px
  3: '0.75rem',   // 12px
  4: '1rem',      // 16px
  5: '1.25rem',   // 20px
  6: '1.5rem',    // 24px
  8: '2rem',      // 32px
  10: '2.5rem',   // 40px
  12: '3rem',     // 48px
  16: '4rem',     // 64px
  20: '5rem',     // 80px
} as const;

export const borderRadius = {
  none: '0',
  sm: '0.375rem',   // 6px
  base: '0.5rem',   // 8px
  md: '0.75rem',    // 12px
  lg: '1rem',       // 16px
  xl: '1.25rem',    // 20px
  '2xl': '1.5rem',  // 24px
  '3xl': '2rem',    // 32px
  full: '9999px',
} as const;

export const shadows = {
  sm: '0 1px 2px 0 rgba(0, 0, 0, 0.3)',
  base: '0 4px 8px -2px rgba(0, 0, 0, 0.3), 0 2px 4px -2px rgba(0, 0, 0, 0.2)',
  md: '0 12px 24px -4px rgba(0, 0, 0, 0.35), 0 4px 8px -4px rgba(0, 0, 0, 0.2)',
  lg: '0 24px 48px -8px rgba(0, 0, 0, 0.4), 0 8px 16px -8px rgba(0, 0, 0, 0.25)',
  xl: '0 32px 64px -12px rgba(0, 0, 0, 0.45), 0 12px 24px -12px rgba(0, 0, 0, 0.3)',
  glow: '0 0 24px rgba(139, 92, 246, 0.35)',
  glowCyan: '0 0 24px rgba(0, 229, 255, 0.3)',
  glowViolet: '0 0 24px rgba(139, 92, 246, 0.35)',
  glowMagenta: '0 0 24px rgba(217, 70, 239, 0.25)',
  glass: '0 8px 32px rgba(0, 0, 0, 0.35), 0 2px 8px rgba(0, 0, 0, 0.2)',
  glassStrong: '0 16px 48px rgba(0, 0, 0, 0.4), 0 4px 16px rgba(0, 0, 0, 0.25)',
  inset: 'inset 0 1px 0 rgba(255, 255, 255, 0.08)',
  insetStrong: 'inset 0 1px 0 rgba(255, 255, 255, 0.15)',
} as const;

export const transitions = {
  fast: '120ms ease-out',
  base: '180ms ease-out',
  slow: '280ms ease-out',
  slower: '400ms ease-out',
} as const;

export const glass = {
  // Glass panel base styles - layered system
  panel: {
    base: {
      background: 'rgba(22, 28, 46, 0.5)',
      backdropFilter: 'blur(20px) saturate(150%)',
      WebkitBackdropFilter: 'blur(20px) saturate(150%)',
      border: '1px solid rgba(139, 92, 246, 0.18)',
      borderRadius: '1rem',
      boxShadow: '0 8px 32px rgba(0, 0, 0, 0.35), 0 2px 8px rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.06)',
    },
    elevated: {
      background: 'rgba(29, 36, 58, 0.65)',
      backdropFilter: 'blur(28px) saturate(180%)',
      WebkitBackdropFilter: 'blur(28px) saturate(180%)',
      border: '1px solid rgba(139, 92, 246, 0.25)',
      borderRadius: '1rem',
      boxShadow: '0 20px 48px rgba(0, 0, 0, 0.4), 0 8px 24px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.1)',
    },
    subtle: {
      background: 'rgba(22, 28, 46, 0.35)',
      backdropFilter: 'blur(16px) saturate(140%)',
      WebkitBackdropFilter: 'blur(16px) saturate(140%)',
      border: '1px solid rgba(139, 92, 246, 0.12)',
      borderRadius: '0.75rem',
      boxShadow: '0 4px 16px rgba(0, 0, 0, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.04)',
    },
  },
  // Glass button styles
  button: {
    primary: {
      background: 'linear-gradient(135deg, #00e5ff 0%, #3b82f6 100%)',
      color: '#05070d',
      border: 'none',
      boxShadow: '0 0 24px rgba(0, 229, 255, 0.4), 0 4px 16px rgba(0, 0, 0, 0.3)',
    },
    secondary: {
      background: 'rgba(22, 28, 46, 0.6)',
      backdropFilter: 'blur(16px)',
      WebkitBackdropFilter: 'blur(16px)',
      color: '#cbd5e1',
      border: '1px solid rgba(139, 92, 246, 0.2)',
      boxShadow: '0 4px 16px rgba(0, 0, 0, 0.2)',
    },
    ghost: {
      background: 'transparent',
      color: '#94a3b8',
      border: '1px solid rgba(139, 92, 246, 0.15)',
      boxShadow: 'none',
    },
    danger: {
      background: 'linear-gradient(135deg, #ef4444 0%, #f59e0b 100%)',
      color: '#f8fafc',
      border: 'none',
      boxShadow: '0 0 24px rgba(239, 68, 68, 0.4), 0 4px 16px rgba(0, 0, 0, 0.3)',
    },
    success: {
      background: 'linear-gradient(135deg, #10b981 0%, #00e5ff 100%)',
      color: '#f8fafc',
      border: 'none',
      boxShadow: '0 0 24px rgba(16, 185, 129, 0.4), 0 4px 16px rgba(0, 0, 0, 0.3)',
    },
  },
  // Glass input styles
  input: {
    base: {
      background: 'rgba(10, 13, 21, 0.6)',
      backdropFilter: 'blur(16px)',
      WebkitBackdropFilter: 'blur(16px)',
      border: '1px solid rgba(139, 92, 246, 0.18)',
      color: '#f8fafc',
    },
    focus: {
      border: '1px solid #00e5ff',
      boxShadow: '0 0 0 3px rgba(0, 229, 255, 0.15), 0 0 24px rgba(0, 229, 255, 0.1)',
    },
  },
} as const;