/** Theme context for liquid-glass (always enabled). */

import { useState, useEffect, useCallback, ReactNode } from 'react';
import { ThemeContext } from './ThemeContextInstance';

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Always enable liquid glass - no toggle
  const [liquidGlassEnabled] = useState(true);

  const applyTheme = useCallback((enabled: boolean) => {
    if (typeof document === 'undefined') return;

    const root = document.documentElement;
    const body = document.body;

    if (enabled) {
      root.classList.add('liquid-glass-enabled');
      root.classList.remove('solid-mode');
      body.classList.add('liquid-glass-enabled');
      body.classList.remove('solid-mode');
    } else {
      root.classList.add('solid-mode');
      root.classList.remove('liquid-glass-enabled');
      body.classList.add('solid-mode');
      body.classList.remove('liquid-glass-enabled');
    }
  }, []);

  useEffect(() => {
    localStorage.setItem('atlasx_liquid_glass', String(liquidGlassEnabled));
    applyTheme(liquidGlassEnabled);
  }, [liquidGlassEnabled, applyTheme]);

  // Apply on mount
  useEffect(() => {
    applyTheme(liquidGlassEnabled);
  }, [applyTheme, liquidGlassEnabled]);

  // Toggle function kept for compatibility but does nothing
  const toggleLiquidGlass = useCallback(() => {
    // No-op - liquid glass is always enabled
  }, []);

  return (
    <ThemeContext.Provider value={{ liquidGlassEnabled, toggleLiquidGlass }}>
      {children}
    </ThemeContext.Provider>
  );
}
