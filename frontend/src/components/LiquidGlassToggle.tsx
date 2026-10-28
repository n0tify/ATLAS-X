/** Liquid Glass toggle component with water-like ripple effect. */

import { useState, useRef } from 'react';
import { useTheme } from '../hooks/useTheme';
import { colors, typography, spacing, borderRadius, transitions, shadows } from '../styles/designTokens';

export function LiquidGlassToggle() {
  const { liquidGlassEnabled, toggleLiquidGlass } = useTheme();
  const [ripple, setRipple] = useState<{ x: number; y: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (rect) {
      setRipple({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      });
      setTimeout(() => setRipple(null), 600);
    }
    toggleLiquidGlass();
  };

  return (
    <button
      ref={buttonRef}
      onClick={handleClick}
      style={{
        fontFamily: typography.fontFamily.primary,
        fontSize: typography.fontSize.sm,
        fontWeight: typography.fontWeight.medium,
        color: colors.text.primary,
        background: liquidGlassEnabled
          ? 'linear-gradient(135deg, rgba(139, 92, 246, 0.85) 0%, rgba(99, 102, 241, 0.85) 100%)'
          : 'rgba(22, 28, 46, 0.7)',
        backdropFilter: liquidGlassEnabled ? 'blur(16px)' : 'none',
        WebkitBackdropFilter: liquidGlassEnabled ? 'blur(16px)' : 'none',
        border: `1px solid ${liquidGlassEnabled ? colors.border.highlight : colors.border.secondary}`,
        borderRadius: borderRadius.md,
        padding: `${spacing[2]} ${spacing[5]}`,
        cursor: 'pointer',
        transition: `all ${transitions.base}`,
        display: 'flex',
        alignItems: 'center',
        gap: spacing[3],
        boxShadow: liquidGlassEnabled ? shadows.glowViolet : shadows.sm,
        position: 'relative',
        overflow: 'hidden',
      }}
      aria-pressed={liquidGlassEnabled}
      aria-label="Toggle liquid glass effect"
    >
      {ripple && (
        <span
          style={{
            position: 'absolute',
            left: ripple.x,
            top: ripple.y,
            width: '0',
            height: '0',
            borderRadius: '50%',
            background: 'rgba(255, 255, 255, 0.25)',
            transform: 'translate(-50%, -50%)',
            animation: 'atlasx-ripple 0.6s ease-out forwards',
            pointerEvents: 'none',
          }}
        />
      )}
      <span
        style={{
          width: '22px',
          height: '22px',
          borderRadius: '50%',
          background: liquidGlassEnabled
            ? `radial-gradient(circle at 30% 30%, ${colors.accent.cyan}, ${colors.accent.violet} 70%)`
            : colors.text.muted,
          transition: `all ${transitions.base}`,
          boxShadow: liquidGlassEnabled
            ? `0 0 16px ${colors.accent.cyan}, inset 0 -2px 4px rgba(0,0,0,0.25)`
            : 'none',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <span
          style={{
            width: '9px',
            height: '9px',
            borderRadius: '50%',
            background: liquidGlassEnabled ? colors.background.primary : 'transparent',
            transition: `all ${transitions.base}`,
          }}
        />
      </span>
      <span style={{ textTransform: 'uppercase', letterSpacing: '0.05em', fontSize: typography.fontSize.xs }}>
        {liquidGlassEnabled ? 'Liquid Glass' : 'Solid'}
      </span>
    </button>
  );
}

/** Water-like toggle button with splash animation */
export function WaterToggle() {
  const { liquidGlassEnabled, toggleLiquidGlass } = useTheme();
  const [splash, setSplash] = useState<{ x: number; y: number } | null>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    const rect = buttonRef.current?.getBoundingClientRect();
    if (rect) {
      setSplash({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
      });
      setTimeout(() => setSplash(null), 800);
    }
    toggleLiquidGlass();
  };

  return (
    <button
      ref={buttonRef}
      onClick={handleClick}
      style={{
        fontFamily: typography.fontFamily.primary,
        fontSize: typography.fontSize.sm,
        fontWeight: typography.fontWeight.medium,
        color: colors.text.primary,
        background: liquidGlassEnabled
          ? `linear-gradient(135deg, ${colors.accent.cyan} 0%, ${colors.accent.violet} 100%)`
          : `linear-gradient(135deg, ${colors.background.tertiary} 0%, ${colors.background.secondary} 100%)`,
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        border: `1px solid ${liquidGlassEnabled ? colors.accent.cyan : colors.border.primary}`,
        borderRadius: '9999px',
        padding: `${spacing[2]} ${spacing[6]}`,
        cursor: 'pointer',
        transition: `all ${transitions.base}`,
        display: 'flex',
        alignItems: 'center',
        gap: spacing[3],
        boxShadow: liquidGlassEnabled
          ? `0 0 30px ${colors.accent.cyan}60, 0 0 60px ${colors.accent.violet}40, inset 0 1px 0 rgba(255,255,255,0.2)`
          : shadows.base,
        position: 'relative',
        overflow: 'hidden',
      }}
      aria-pressed={liquidGlassEnabled}
      aria-label="Toggle liquid glass effect"
    >
      {/* Water surface */}
      <span
        style={{
          position: 'absolute',
          inset: 0,
          background: liquidGlassEnabled
            ? `linear-gradient(180deg, transparent 40%, rgba(255,255,255,0.1) 50%, transparent 60%)`
            : 'transparent',
          borderRadius: '9999px',
          opacity: liquidGlassEnabled ? 1 : 0,
          transition: 'opacity 300ms ease',
        }}
      />
      {/* Splash ripple */}
      {splash && (
        <span
          style={{
            position: 'absolute',
            left: splash.x,
            top: splash.y,
            width: '0',
            height: '0',
            borderRadius: '50%',
            background: `radial-gradient(circle, ${colors.accent.cyan}80, transparent 70%)`,
            transform: 'translate(-50%, -50%)',
            animation: 'atlasx-splash 0.8s ease-out forwards',
            pointerEvents: 'none',
            zIndex: 1,
          }}
        />
      )}
      {/* Water droplet icon */}
      <span
        style={{
          position: 'relative',
          zIndex: 2,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '28px',
          height: '28px',
          borderRadius: '50%',
          background: liquidGlassEnabled
            ? `linear-gradient(135deg, ${colors.accent.cyan} 0%, ${colors.accent.violet} 100%)`
            : colors.background.tertiary,
          boxShadow: liquidGlassEnabled
            ? `0 0 20px ${colors.accent.cyan}80, inset 0 -2px 4px rgba(0,0,0,0.3)`
            : `inset 0 2px 4px rgba(0,0,0,0.2)`,
          transition: `all ${transitions.base}`,
        }}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke={liquidGlassEnabled ? colors.background.primary : colors.text.tertiary}
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ transition: `all ${transitions.base}` }}
        >
          {liquidGlassEnabled ? (
            <>
              <path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z" />
              <path d="M12 2.69v18.62" />
            </>
          ) : (
            <path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z" />
          )}
        </svg>
      </span>
      <span
        style={{
          position: 'relative',
          zIndex: 2,
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          fontSize: typography.fontSize.xs,
          transition: `all ${transitions.base}`,
        }}
      >
        {liquidGlassEnabled ? 'Liquid Glass' : 'Solid Mode'}
      </span>
    </button>
  );
}

/** ATLAS-X Custom Logo Component */
export function AtlasXLogo({ size = 'md', animated = false }: { size?: 'sm' | 'md' | 'lg' | 'xl'; animated?: boolean }) {
  const sizeMap = {
    sm: { icon: 24, text: 18, gap: 8 },
    md: { icon: 32, text: 24, gap: 10 },
    lg: { icon: 48, text: 36, gap: 14 },
    xl: { icon: 64, text: 48, gap: 18 },
  };
  const { icon, text, gap } = sizeMap[size];

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap,
      }}
    >
      <div
        style={{
          width: icon,
          height: icon,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          position: 'relative',
        }}
      >
        {/* Outer ring */}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            borderRadius: '50%',
            border: `2px solid ${colors.accent.cyan}40`,
            animation: animated ? 'atlasx-rotate 20s linear infinite' : 'none',
          }}
        />
        {/* Inner ring */}
        <div
          style={{
            position: 'absolute',
            inset: 4,
            borderRadius: '50%',
            border: `2px solid ${colors.accent.violet}40`,
            animation: animated ? 'atlasx-rotate-reverse 30s linear infinite' : 'none',
          }}
        />
        {/* Core hexagon */}
        <svg
          width={icon * 0.6}
          height={icon * 0.6}
          viewBox="0 0 24 24"
          fill="none"
          style={{
            position: 'relative',
            zIndex: 1,
            filter: animated ? 'drop-shadow(0 0 12px #00e5ff) drop-shadow(0 0 24px #8b5cf6)' : 'drop-shadow(0 0 8px #00e5ff)',
            animation: animated ? 'atlasx-pulse-scale 3s ease-in-out infinite' : 'none',
          }}
        >
          <path
            d="M12 2L2 7l10 5 10-5-10-5-10 5z"
            stroke={colors.accent.cyan}
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <path
            d="M2 7l10 5 10-5"
            stroke={colors.accent.violet}
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            opacity="0.6"
          />
          <circle
            cx="12"
            cy="12"
            r="3"
            fill={colors.accent.cyan}
            opacity="0.9"
          />
        </svg>
        {/* Sparkle particles */}
        {animated && [...Array(6)].map((_, i) => (
          <div
            key={i}
            style={{
              position: 'absolute',
              width: 4,
              height: 4,
              borderRadius: '50%',
              background: i % 2 === 0 ? colors.accent.cyan : colors.accent.violet,
              top: '50%',
              left: '50%',
              transform: `translate(-50%, -50%) rotate(${i * 60}deg) translateY(-${icon * 0.45}px) rotate(-${i * 60}deg)`,
              animation: `atlasx-sparkle 2s ease-in-out infinite ${i * 0.3}s`,
              opacity: 0,
              pointerEvents: 'none',
            }}
          />
        ))}
      </div>
      <span
        style={{
          fontSize: text,
          fontWeight: 700,
          letterSpacing: '0.15em',
          color: colors.text.primary,
          background: `linear-gradient(135deg, ${colors.text.primary} 0%, ${colors.accent.cyan} 50%, ${colors.accent.violet} 100%)`,
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
          backgroundClip: 'text',
        }}
      >
        ATLAS-X
      </span>
    </div>
  );
}

/** Glass morphism card with specular highlight */
export function GlassMorphismCard({
  children,
  className = '',
  style = {},
  elevated = false,
  hoverable = false,
  onClick,
  padding = 6,
}: {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  elevated?: boolean;
  hoverable?: boolean;
  onClick?: () => void;
  padding?: keyof typeof spacing;
}) {
  const { liquidGlassEnabled } = useTheme();
  const [hovered, setHovered] = useState(false);

  const baseStyle: React.CSSProperties = {
    background: elevated
      ? `rgba(29, 36, 58, ${hovered ? 0.7 : 0.55})`
      : `rgba(255, 255, 255, ${hovered ? 0.06 : 0.03})`,
    backdropFilter: liquidGlassEnabled ? 'blur(24px)' : 'none',
    WebkitBackdropFilter: liquidGlassEnabled ? 'blur(24px)' : 'none',
    border: `1px solid ${hovered ? colors.accent.cyan : colors.border.primary}`,
    borderRadius: borderRadius.xl,
    padding: spacing[padding],
    boxShadow: hovered
      ? `${shadows.lg}, 0 0 40px ${colors.accent.cyan}20`
      : elevated
        ? shadows.lg
        : shadows.base,
    transition: `all ${transitions.base}`,
    cursor: hoverable ? 'pointer' : 'default',
    ...style,
  };

  // Specular highlight overlay
  const highlightStyle: React.CSSProperties = {
    position: 'absolute',
    inset: 0,
    borderRadius: borderRadius.xl,
    background: `linear-gradient(135deg, rgba(255,255,255,0.08) 0%, transparent 50%)`,
    pointerEvents: 'none',
    opacity: hovered ? 1 : 0.3,
    transition: `opacity ${transitions.base}`,
  };

  return (
    <div
      className={className}
      style={{ position: 'relative', ...baseStyle }}
      onClick={onClick}
      onMouseEnter={() => hoverable && setHovered(true)}
      onMouseLeave={() => hoverable && setHovered(false)}
    >
      <div style={highlightStyle} />
      {children}
    </div>
  );
}

/** Liquid progress ring for loading states */
export function LiquidProgressRing({
  progress = 0,
  size = 'md',
  color = 'cyan',
  thickness = 4,
}: {
  progress?: number;
  size?: 'sm' | 'md' | 'lg';
  color?: 'cyan' | 'violet' | 'success';
  thickness?: number;
}) {
  const sizeMap = { sm: 40, md: 64, lg: 96 };
  const colorMap = {
    cyan: colors.accent.cyan,
    violet: colors.accent.violet,
    success: colors.accent.success,
  };
  const radius = (sizeMap[size] - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (progress / 100) * circumference;

  return (
    <svg width={sizeMap[size]} height={sizeMap[size]} style={{ transform: 'rotate(-90deg)' }}>
      <circle
        cx={sizeMap[size] / 2}
        cy={sizeMap[size] / 2}
        r={radius}
        fill="none"
        stroke={colors.border.primary}
        strokeWidth={thickness}
      />
      <circle
        cx={sizeMap[size] / 2}
        cy={sizeMap[size] / 2}
        r={radius}
        fill="none"
        stroke={colorMap[color]}
        strokeWidth={thickness}
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        style={{
          transition: `stroke-dashoffset ${transitions.slow} ease-out`,
          filter: `drop-shadow(0 0 8px ${colorMap[color]})`,
        }}
      />
    </svg>
  );
}