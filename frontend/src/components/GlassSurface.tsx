/** Glass surface component for liquid-glass UI. */

import React from 'react';
import { colors, borderRadius, shadows } from '../styles/designTokens';

interface GlassSurfaceProps {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
  blur?: string;
  opacity?: number;
}

export function GlassSurface({ children, className, style, blur = '20px', opacity = 0.6 }: GlassSurfaceProps) {
  const surfaceStyle: React.CSSProperties = {
    background: `rgba(20, 27, 44, ${opacity})`,
    backdropFilter: `blur(${blur})`,
    WebkitBackdropFilter: `blur(${blur})`,
    border: `1px solid ${colors.glass.border}`,
    borderRadius: borderRadius.lg,
    boxShadow: shadows.glass,
    ...style,
  };

  return (
    <div className={className} style={surfaceStyle}>
      {children}
    </div>
  );
}
