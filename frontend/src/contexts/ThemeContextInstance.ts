/** Theme context instance (non-component) for Fast Refresh compatibility. */

import { createContext } from 'react';

interface ThemeContextType {
  liquidGlassEnabled: boolean;
  toggleLiquidGlass: () => void;
}

export const ThemeContext = createContext<ThemeContextType | undefined>(undefined);
