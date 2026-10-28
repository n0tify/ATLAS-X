/** Liquid Glass UI Components - Premium spatial UI components with glass morphism effects. */

import React from 'react';
import { colors, typography, spacing, borderRadius, shadows, transitions } from '../styles/designTokens';

interface GlassPanelProps {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  elevated?: boolean;
  interactive?: boolean;
  padding?: keyof typeof spacing;
  blur?: 'sm' | 'md' | 'lg' | 'xl';
}

export function GlassPanel({
  children,
  className = '',
  style = {},
  elevated = false,
  interactive = false,
  padding = 6,
  blur = 'lg',
}: GlassPanelProps) {
  const blurValues = {
    sm: 'blur(8px)',
    md: 'blur(16px)',
    lg: 'blur(24px)',
    xl: 'blur(32px)',
  };

  const baseStyle: React.CSSProperties = {
    background: elevated
      ? `rgba(30, 41, 59, 0.6)`
      : `rgba(30, 41, 59, 0.4)`,
    backdropFilter: blurValues[blur],
    WebkitBackdropFilter: blurValues[blur],
    border: `1px solid ${colors.border.primary}`,
    borderRadius: borderRadius.xl,
    padding: spacing[padding],
    boxShadow: elevated ? shadows.lg : shadows.base,
    transition: `all ${transitions.base}`,
    ...style,
  };

  if (interactive) {
    baseStyle.cursor = 'pointer';
  }

  return (
    <div className={className} style={baseStyle}>
      {children}
    </div>
  );
}

interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  hoverable?: boolean;
  onClick?: () => void;
  padding?: keyof typeof spacing;
}

export function GlassCard({
  children,
  className = '',
  style = {},
  hoverable = false,
  onClick,
  padding = 4,
}: GlassCardProps) {
  const baseStyle: React.CSSProperties = {
    background: `rgba(255, 255, 255, 0.03)`,
    backdropFilter: 'blur(20px)',
    WebkitBackdropFilter: 'blur(20px)',
    border: `1px solid ${colors.border.primary}`,
    borderRadius: borderRadius.lg,
    padding: spacing[padding],
    boxShadow: shadows.base,
    transition: `all ${transitions.base}`,
    ...style,
  };

  if (hoverable) {
    baseStyle.cursor = 'pointer';
  }

  return (
    <div
      className={className}
      style={baseStyle}
      onClick={onClick}
      onMouseEnter={(e) => {
        if (hoverable) {
          e.currentTarget.style.background = `rgba(255, 255, 255, 0.06)`;
          e.currentTarget.style.borderColor = colors.accent.cyan;
          e.currentTarget.style.boxShadow = shadows.glow;
        }
      }}
      onMouseLeave={(e) => {
        if (hoverable) {
          e.currentTarget.style.background = `rgba(255, 255, 255, 0.03)`;
          e.currentTarget.style.borderColor = colors.border.primary;
          e.currentTarget.style.boxShadow = shadows.base;
        }
      }}
    >
      {children}
    </div>
  );
}

interface LiquidButtonProps {
  children: React.ReactNode;
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost' | 'success';
  size?: 'sm' | 'md' | 'lg';
  disabled?: boolean;
  loading?: boolean;
  onClick?: () => void;
  style?: React.CSSProperties;
  className?: string;
  fullWidth?: boolean;
  icon?: React.ReactNode;
  iconPosition?: 'left' | 'right';
  type?: 'button' | 'submit' | 'reset';
}

export function LiquidButton({
  children,
  variant = 'primary',
  size = 'md',
  disabled = false,
  loading = false,
  onClick,
  style = {},
  className = '',
  fullWidth = false,
  icon,
  iconPosition = 'left',
  type = 'button',
}: LiquidButtonProps) {
  const sizeStyles = {
    sm: { padding: `${spacing[2]} ${spacing[4]}`, fontSize: typography.fontSize.sm, gap: spacing[2] },
    md: { padding: `${spacing[3]} ${spacing[6]}`, fontSize: typography.fontSize.base, gap: spacing[3] },
    lg: { padding: `${spacing[4]} ${spacing[8]}`, fontSize: typography.fontSize.lg, gap: spacing[4] },
  };

  const variantStyles = {
    primary: {
      background: `linear-gradient(135deg, ${colors.accent.cyan} 0%, ${colors.accent.blue} 100%)`,
      color: colors.text.primary,
      border: 'none',
      boxShadow: shadows.glow,
    },
    secondary: {
      background: `rgba(255, 255, 255, 0.05)`,
      color: colors.text.secondary,
      border: `1px solid ${colors.border.primary}`,
      boxShadow: 'none',
    },
    danger: {
      background: `linear-gradient(135deg, ${colors.accent.error} 0%, ${colors.accent.warning} 100%)`,
      color: colors.text.primary,
      border: 'none',
      boxShadow: `0 0 20px ${colors.accent.error}40`,
    },
    ghost: {
      background: 'transparent',
      color: colors.text.secondary,
      border: `1px solid ${colors.border.primary}`,
      boxShadow: 'none',
    },
    success: {
      background: `linear-gradient(135deg, ${colors.accent.success} 0%, ${colors.accent.cyan} 100%)`,
      color: colors.text.primary,
      border: 'none',
      boxShadow: `0 0 20px ${colors.accent.success}40`,
    },
  };

  const baseStyle: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: borderRadius.base,
    fontSize: sizeStyles[size].fontSize,
    fontWeight: typography.fontWeight.semibold,
    padding: sizeStyles[size].padding,
    gap: sizeStyles[size].gap,
    cursor: disabled || loading ? 'not-allowed' : 'pointer',
    fontFamily: typography.fontFamily.primary,
    transition: `all ${transitions.base}`,
    opacity: disabled || loading ? 0.6 : 1,
    width: fullWidth ? '100%' : 'auto',
    ...variantStyles[variant],
    ...style,
  };

  return (
    <button
      className={className}
      style={baseStyle}
      onClick={onClick}
      disabled={disabled || loading}
      aria-disabled={disabled || loading}
      type={type}
    >
      {loading && (
        <span style={{ display: 'inline-flex', alignItems: 'center' }}>
          <span style={{
            width: '16px',
            height: '16px',
            border: '2px solid currentColor',
            borderRightColor: 'transparent',
            borderRadius: '50%',
            animation: 'spin 1s linear infinite',
            marginRight: iconPosition === 'right' ? 0 : sizeStyles[size].gap,
          }} />
          {children}
        </span>
      )}
      {!loading && (
        <>
          {icon && iconPosition === 'left' && <span style={{ display: 'flex', alignItems: 'center' }}>{icon}</span>}
          <span>{children}</span>
          {icon && iconPosition === 'right' && <span style={{ display: 'flex', alignItems: 'center' }}>{icon}</span>}
        </>
      )}
    </button>
  );
}

interface LiquidInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: 'text' | 'password' | 'email' | 'number' | 'textarea';
  label?: string;
  error?: string;
  disabled?: boolean;
  required?: boolean;
  minLength?: number;
  maxLength?: number;
  autoComplete?: string;
  style?: React.CSSProperties;
  className?: string;
  icon?: React.ReactNode;
  rows?: number;
  id?: string;
  min?: number;
  max?: number;
}

export function LiquidInput({
  value,
  onChange,
  placeholder,
  type = 'text',
  label,
  error,
  disabled = false,
  required = false,
  style = {},
  className = '',
  icon,
  maxLength,
  minLength,
  autoComplete,
  rows = 3,
  id,
  min,
  max,
}: LiquidInputProps) {
  const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: `${spacing[3]} ${spacing[4]}`,
    borderRadius: borderRadius.base,
    border: `1px solid ${error ? colors.accent.error : colors.border.primary}`,
    backgroundColor: colors.background.tertiary,
    color: colors.text.primary,
    fontSize: typography.fontSize.base,
    fontFamily: typography.fontFamily.primary,
    outline: 'none',
    transition: `all ${transitions.base}`,
    boxSizing: 'border-box',
    ...style,
  };

  if (disabled) {
    inputStyle.opacity = 0.6;
    inputStyle.cursor = 'not-allowed';
  }

  if (type === 'textarea') {
    inputStyle.resize = 'vertical';
    inputStyle.minHeight = `${rows * 2.5}rem`;
  }

  return (
    <div className={className} style={{ display: 'flex', flexDirection: 'column', gap: spacing[2], width: '100%' }}>
      {label && (
        <label style={{
          fontSize: typography.fontSize.sm,
          fontWeight: typography.fontWeight.medium,
          color: colors.text.secondary,
        }}>
          {label}
          {required && <span style={{ color: colors.accent.error, marginLeft: spacing[1] }}>*</span>}
        </label>
      )}
      <div style={{ position: 'relative', display: 'flex', alignItems: type === 'textarea' ? 'flex-start' : 'center' }}>
        {icon && (
          <span style={{
            position: 'absolute',
            left: spacing[4],
            top: type === 'textarea' ? spacing[3] : '50%',
            transform: type === 'textarea' ? 'none' : 'translateY(-50%)',
            color: colors.text.tertiary,
            pointerEvents: 'none',
            zIndex: 1,
          }}>
            {icon}
          </span>
        )}
        {type === 'textarea' ? (
          <textarea
            id={id}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            disabled={disabled}
            maxLength={maxLength}
            rows={rows}
            style={{
              ...inputStyle,
              paddingLeft: icon ? spacing[10] : spacing[4],
              fontFamily: typography.fontFamily.primary,
            }}
          />
        ) : (
          <input
            id={id}
            type={type}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            disabled={disabled}
            maxLength={maxLength}
            minLength={minLength}
            autoComplete={autoComplete}
            min={min}
            max={max}
            style={{
              ...inputStyle,
              paddingLeft: icon ? spacing[10] : spacing[4],
            }}
          />
        )}
      </div>
      {error && (
        <span style={{
          fontSize: typography.fontSize.xs,
          color: colors.accent.error,
          display: 'flex',
          alignItems: 'center',
          gap: spacing[1],
        }}>
          ⚠ {error}
        </span>
      )}
    </div>
  );
}

interface LiquidTabsProps {
  tabs: Array<{ id: string; label: string; disabled?: boolean }>;
  activeTab: string;
  onChange: (tabId: string) => void;
  style?: React.CSSProperties;
  className?: string;
}

export function LiquidTabs({
  tabs,
  activeTab,
  onChange,
  style = {},
  className = '',
}: LiquidTabsProps) {
  return (
    <div className={className} style={{ display: 'flex', gap: spacing[2], marginBottom: spacing[6], borderBottom: `1px solid ${colors.border.primary}`, paddingBottom: spacing[2], flexWrap: 'wrap', ...style }}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => !tab.disabled && onChange(tab.id)}
          disabled={tab.disabled}
          style={{
            padding: `${spacing[3]} ${spacing[6]}`,
            borderRadius: borderRadius.base,
            border: `1px solid ${colors.border.primary}`,
            background: activeTab === tab.id ? `rgba(0, 212, 255, 0.1)` : 'transparent',
            borderColor: activeTab === tab.id ? colors.accent.cyan : colors.border.primary,
            color: activeTab === tab.id ? colors.accent.cyan : tab.disabled ? colors.text.muted : colors.text.secondary,
            cursor: tab.disabled ? 'not-allowed' : 'pointer',
            fontSize: typography.fontSize.sm,
            fontWeight: typography.fontWeight.medium,
            transition: `all ${transitions.base}`,
            opacity: tab.disabled ? 0.5 : 1,
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

interface LiquidBadgeProps {
  children: React.ReactNode;
  variant?: 'default' | 'success' | 'warning' | 'error' | 'info' | 'cyan' | 'violet';
  size?: 'sm' | 'md' | 'lg';
  style?: React.CSSProperties;
  className?: string;
}

export function LiquidBadge({
  children,
  variant = 'default',
  size = 'md',
  style = {},
  className = '',
}: LiquidBadgeProps) {
  const variantStyles = {
    default: { background: `rgba(255, 255, 255, 0.1)`, color: colors.text.secondary, border: `1px solid ${colors.border.primary}` },
    success: { background: `${colors.accent.success}1A`, color: colors.accent.success, border: `1px solid ${colors.accent.success}40` },
    warning: { background: `${colors.accent.warning}1A`, color: colors.accent.warning, border: `1px solid ${colors.accent.warning}40` },
    error: { background: `${colors.accent.error}1A`, color: colors.accent.error, border: `1px solid ${colors.accent.error}40` },
    info: { background: `${colors.accent.blue}1A`, color: colors.accent.blue, border: `1px solid ${colors.accent.blue}40` },
    cyan: { background: `${colors.accent.cyan}1A`, color: colors.accent.cyan, border: `1px solid ${colors.accent.cyan}40` },
    violet: { background: `${colors.accent.violet}1A`, color: colors.accent.violet, border: `1px solid ${colors.accent.violet}40` },
  };

  const sizeStyles = {
    sm: { padding: `${spacing[1]} ${spacing[2]}`, fontSize: typography.fontSize.xs, borderRadius: borderRadius.sm },
    md: { padding: `${spacing[1]} ${spacing[3]}`, fontSize: typography.fontSize.sm, borderRadius: borderRadius.base },
    lg: { padding: `${spacing[2]} ${spacing[4]}`, fontSize: typography.fontSize.base, borderRadius: borderRadius.lg },
  };

  return (
    <span
      className={className}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: sizeStyles[size].fontSize,
        fontWeight: typography.fontWeight.medium,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        padding: sizeStyles[size].padding,
        borderRadius: sizeStyles[size].borderRadius,
        ...variantStyles[variant],
        ...style,
      }}
    >
      {children}
    </span>
  );
}

export function LiquidSpinner({ size = 'md', color = 'cyan' }: { size?: 'sm' | 'md' | 'lg'; color?: 'cyan' | 'violet' | 'white' }) {
  const sizeMap = { sm: 24, md: 40, lg: 56 };
  const colorMap = {
    cyan: colors.accent.cyan,
    violet: colors.accent.violet,
    white: colors.text.primary,
  };

  return (
    <div
      style={{
        width: sizeMap[size],
        height: sizeMap[size],
        border: `3px solid ${colors.border.primary}`,
        borderTopColor: colorMap[color],
        borderRadius: '50%',
        animation: 'spin 1s linear infinite',
      }}
    />
  );
}

export function LiquidProgress({ value = 0, max = 100, size = 'md', color = 'cyan', showLabel = false }: { value?: number; max?: number; size?: 'sm' | 'md' | 'lg'; color?: 'cyan' | 'violet' | 'success'; showLabel?: boolean }) {
  const percentage = Math.min(100, Math.max(0, (value / max) * 100));
  const colorMap = {
    cyan: colors.accent.cyan,
    violet: colors.accent.violet,
    success: colors.accent.success,
  };
  const heightMap = { sm: 4, md: 6, lg: 10 };

  return (
    <div style={{ width: '100%' }}>
      <div style={{
        width: '100%',
        height: heightMap[size],
        backgroundColor: colors.background.tertiary,
        borderRadius: heightMap[size],
        overflow: 'hidden',
        position: 'relative',
      }}>
        <div
          style={{
            width: `${percentage}%`,
            height: '100%',
            background: `linear-gradient(90deg, ${colorMap[color]}, ${colorMap[color]}dd)`,
            borderRadius: heightMap[size],
            transition: `width ${transitions.slow} ease-out`,
          }}
        />
      </div>
      {showLabel && (
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: spacing[2], fontSize: typography.fontSize.xs, color: colors.text.tertiary }}>
          <span>{value}</span>
          <span>{max}</span>
        </div>
      )}
    </div>
  );
}

export function LiquidTooltip({ children, content, position = 'top' }: { children: React.ReactElement; content: React.ReactNode; position?: 'top' | 'bottom' | 'left' | 'right' }) {
  const [visible, setVisible] = React.useState(false);

  const positions = {
    top: { bottom: '100%', left: '50%', transform: 'translateX(-50%) translateY(-8px)' },
    bottom: { top: '100%', left: '50%', transform: 'translateX(-50%) translateY(8px)' },
    left: { right: '100%', top: '50%', transform: 'translateY(-50%) translateX(-8px)' },
    right: { left: '100%', top: '50%', transform: 'translateY(-50%) translateX(8px)' },
  };

  return (
    <div style={{ position: 'relative', display: 'inline-block' }} onMouseEnter={() => setVisible(true)} onMouseLeave={() => setVisible(false)}>
      {React.cloneElement(children, { style: { ...children.props.style, cursor: 'help' } })}
      {visible && (
        <div
          style={{
            position: 'absolute',
            ...positions[position],
            zIndex: 1000,
            padding: `${spacing[2]} ${spacing[3]}`,
            background: `rgba(17, 24, 39, 0.95)`,
            backdropFilter: 'blur(10px)',
            border: `1px solid ${colors.border.primary}`,
            borderRadius: borderRadius.base,
            fontSize: typography.fontSize.sm,
            color: colors.text.secondary,
            whiteSpace: 'nowrap',
            boxShadow: shadows.lg,
            animation: 'fadeIn 0.15s ease-out',
          }}
        >
          {content}
        </div>
      )}
    </div>
  );
}

interface LiquidSelectOption {
  value: string;
  label: string;
}

interface LiquidSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: LiquidSelectOption[];
  placeholder?: string;
  label?: string;
  error?: string;
  disabled?: boolean;
  required?: boolean;
  style?: React.CSSProperties;
  className?: string;
}

export function LiquidSelect(props: LiquidSelectProps) {
  const {
    value,
    onChange,
    options,
    placeholder,
    label,
    error,
    disabled = false,
    required = false,
    style = {},
    className = '',
  } = props;

  const baseSelectStyle: React.CSSProperties = {
    width: '100%',
    padding: `${spacing[3]} ${spacing[4]}`,
    borderRadius: borderRadius.base,
    border: `1px solid ${error ? colors.accent.error : colors.border.primary}`,
    backgroundColor: colors.background.tertiary,
    color: colors.text.primary,
    fontSize: typography.fontSize.base,
    fontFamily: typography.fontFamily.primary,
    outline: 'none',
    transition: `all ${transitions.base}`,
    boxSizing: 'border-box',
    ...style,
  };

  if (disabled) {
    baseSelectStyle.opacity = 0.5;
    baseSelectStyle.cursor = 'not-allowed';
  }

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => onChange(e.target.value);

  return (
    <div className={className} style={{ display: 'flex', flexDirection: 'column', gap: spacing[2], width: '100%' }}>
      {label && (
        <label style={{
          fontSize: typography.fontSize.sm,
          fontWeight: typography.fontWeight.medium,
          color: colors.text.secondary,
        }}>
          {label}
          {required && <span style={{ color: colors.accent.error, marginLeft: spacing[1] }}>*</span>}
        </label>
      )}
      <select
        value={value}
        onChange={handleChange}
        disabled={disabled}
        required={required}
        style={baseSelectStyle}
      >
        {placeholder && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map(option => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {error && (
        <span style={{
          fontSize: typography.fontSize.xs,
          color: colors.accent.error,
          display: 'flex',
          alignItems: 'center',
          gap: spacing[1],
        }}>
          ⚠ {error}
        </span>
      )}
    </div>
  );
}