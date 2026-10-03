import React, { createContext, useContext, useEffect, useCallback } from 'react';
import { applyThemeTokens, buildMcpHostStyles } from '../theme/theme-tokens';
import type { McpUiHostStyles } from '@modelcontextprotocol/ext-apps/app-bridge';

type ThemePreference = 'light' | 'dark' | 'system';
type ResolvedTheme = 'light' | 'dark';

interface ThemeContextValue {
  userThemePreference: ThemePreference;
  setUserThemePreference: (pref: ThemePreference) => void;
  resolvedTheme: ResolvedTheme;
  mcpHostStyles: McpUiHostStyles;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

/**
 * NGOPilot ships a single light paper theme. The OS colour scheme, a stored
 * `theme: dark` preference and theme broadcasts from other windows are all
 * ignored so every surface — including portals, native controls and MCP apps —
 * renders against the same light tokens.
 */
function applyLightThemeToDocument(): void {
  document.documentElement.classList.add('light');
  document.documentElement.classList.remove('dark');
  document.documentElement.style.colorScheme = 'light';
}

const mcpHostStyles = buildMcpHostStyles();

interface ThemeProviderProps {
  children: React.ReactNode;
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  useEffect(() => {
    applyLightThemeToDocument();
    applyThemeTokens('light');
  }, []);

  // Kept for API compatibility with existing consumers; light is the only theme.
  const setUserThemePreference = useCallback((_preference: ThemePreference) => {
    applyLightThemeToDocument();
  }, []);

  const value: ThemeContextValue = {
    userThemePreference: 'light',
    setUserThemePreference,
    resolvedTheme: 'light',
    mcpHostStyles,
  };

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
