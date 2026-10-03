/**
 * Theme tokens — the single source of truth for all MCP semantic token values.
 *
 * NGOPilot is light-only: one warm paper palette (the CareFlow Atlas system)
 * is applied to :root before first paint (see renderer.tsx) and re-applied by
 * ThemeProvider. The OS colour scheme and any stored dark preference are
 * ignored. Every key in McpUiStyleVariableKey must be present; the TypeScript
 * compiler enforces this when the SDK adds a key.
 *
 * These tokens serve two purposes:
 *  1. NGOPilot UI — applied to :root.
 *  2. MCP apps — passed as plain light values in hostContext.styles.variables.
 */
import type {
  McpUiHostStyles,
  McpUiStyleVariableKey,
  McpUiStyles,
} from '@modelcontextprotocol/ext-apps/app-bridge';

type ThemeTokens = Record<McpUiStyleVariableKey, string>;

// Non-colour keys (typography, radii, border widths).
type BaseTokenKey = Extract<
  McpUiStyleVariableKey,
  `--font-${string}` | `--border-radius-${string}` | `--border-width-${string}`
>;

type ColorTokenKey = Exclude<McpUiStyleVariableKey, BaseTokenKey>;

// ---------------------------------------------------------------------------
// Base tokens — typography, radii and borders
// ---------------------------------------------------------------------------
const baseTokens: Pick<ThemeTokens, BaseTokenKey> = {
  // Typography — families
  '--font-sans': "'Inter', 'Noto Sans TC', -apple-system, BlinkMacSystemFont, sans-serif",
  '--font-mono': 'monospace',

  // Typography — weights
  '--font-weight-normal': '400',
  '--font-weight-medium': '500',
  '--font-weight-semibold': '600',
  '--font-weight-bold': '700',

  // Typography — text sizes
  '--font-text-xs-size': '0.75rem',
  '--font-text-sm-size': '0.875rem',
  '--font-text-md-size': '1rem',
  '--font-text-lg-size': '1.125rem',

  // Typography — heading sizes
  '--font-heading-xs-size': '1rem',
  '--font-heading-sm-size': '1.125rem',
  '--font-heading-md-size': '1.25rem',
  '--font-heading-lg-size': '1.5rem',
  '--font-heading-xl-size': '1.875rem',
  '--font-heading-2xl-size': '2.25rem',
  '--font-heading-3xl-size': '3rem',

  // Typography — text line heights
  '--font-text-xs-line-height': '1rem',
  '--font-text-sm-line-height': '1.25rem',
  '--font-text-md-line-height': '1.5rem',
  '--font-text-lg-line-height': '1.75rem',

  // Typography — heading line heights
  '--font-heading-xs-line-height': '1.5rem',
  '--font-heading-sm-line-height': '1.75rem',
  '--font-heading-md-line-height': '1.75rem',
  '--font-heading-lg-line-height': '2rem',
  '--font-heading-xl-line-height': '2.25rem',
  '--font-heading-2xl-line-height': '2.5rem',
  '--font-heading-3xl-line-height': '3.5rem',

  // Border radius
  '--border-radius-xs': '2px',
  '--border-radius-sm': '2px',
  '--border-radius-md': '3px',
  '--border-radius-lg': '3px',
  '--border-radius-xl': '4px',
  '--border-radius-full': '9999px',

  // Border width
  '--border-width-regular': '1px',
};

// Colour and shadow tokens.
type ColorTokens = Pick<ThemeTokens, ColorTokenKey>;

// ---------------------------------------------------------------------------
// Light paper palette — colours & shadows
// ---------------------------------------------------------------------------
const lightColorTokens: ColorTokens = {
  // Backgrounds
  '--color-background-primary': '#fffdf8',
  '--color-background-secondary': '#f7f4ec',
  '--color-background-tertiary': '#efe8da',
  '--color-background-inverse': '#1d2622',
  '--color-background-ghost': 'transparent',
  '--color-background-info': '#7d3b27',
  '--color-background-danger': '#6b2419',
  '--color-background-success': '#7d3b27',
  '--color-background-warning': '#9a6420',
  '--color-background-disabled': '#efe8da',

  // Text
  '--color-text-primary': '#1d2622',
  '--color-text-secondary': '#5f5b52',
  '--color-text-tertiary': '#7a766b',
  '--color-text-inverse': '#fffdf8',
  '--color-text-ghost': '#6b675d',
  '--color-text-info': '#7d3b27',
  '--color-text-danger': '#6b2419',
  '--color-text-success': '#7d3b27',
  '--color-text-warning': '#7a4c12',
  '--color-text-disabled': '#969083',

  // Borders
  '--color-border-primary': '#ddd6c6',
  '--color-border-secondary': '#cbc3b1',
  '--color-border-tertiary': '#969083',
  '--color-border-inverse': '#1d2622',
  '--color-border-ghost': 'transparent',
  '--color-border-info': '#7d3b27',
  '--color-border-danger': '#6b2419',
  '--color-border-success': '#7d3b27',
  '--color-border-warning': '#9a6420',
  '--color-border-disabled': '#efe8da',

  // Rings
  '--color-ring-primary': '#7d3b27',
  '--color-ring-secondary': '#ddd6c6',
  '--color-ring-inverse': '#fffdf8',
  '--color-ring-info': '#7d3b27',
  '--color-ring-danger': '#6b2419',
  '--color-ring-success': '#7d3b27',
  '--color-ring-warning': '#9a6420',

  // Shadows
  '--shadow-hairline': '0 0 0 1px rgba(31, 28, 24, 0.06)',
  '--shadow-sm': '0 1px 2px 0 rgba(31, 28, 24, 0.06)',
  '--shadow-md': '0 8px 24px rgba(58, 46, 26, 0.10)',
  '--shadow-lg': '0 14px 36px rgba(58, 46, 26, 0.14)',
};

// ---------------------------------------------------------------------------
// Merged token maps — used by applyThemeTokens() and buildMcpHostStyles()
// ---------------------------------------------------------------------------
export const lightTokens: ThemeTokens = { ...baseTokens, ...lightColorTokens };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// @font-face rules passed to MCP apps so sandboxed iframes can load host fonts.
const HOST_FONT_CSS = `
@font-face {
  font-family: 'Cash Sans';
  src: url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff2/CashSans-Light.woff2) format('woff2'),
       url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff/CashSans-Light.woff) format('woff');
  font-weight: 300;
  font-style: normal;
}
@font-face {
  font-family: 'Cash Sans';
  src: url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff2/CashSans-Regular.woff2) format('woff2'),
       url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff/CashSans-Regular.woff) format('woff');
  font-weight: 400;
  font-style: normal;
}
@font-face {
  font-family: 'Cash Sans';
  src: url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff2/CashSans-Medium.woff2) format('woff2'),
       url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff/CashSans-Medium.woff) format('woff');
  font-weight: 500;
  font-style: normal;
}
@font-face {
  font-family: 'Cash Sans';
  src: url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff2/CashSans-Bold.woff2) format('woff2'),
       url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff/CashSans-Bold.woff) format('woff');
  font-weight: 700;
  font-style: normal;
}
`.trim();

/**
 * Build the McpUiHostStyles object for MCP apps. NGOPilot is light-only, so
 * every key carries its plain light value. css.fonts provides @font-face rules
 * so sandboxed apps can load host fonts.
 */
export function buildMcpHostStyles(): McpUiHostStyles {
  const variables: McpUiStyles = {} as McpUiStyles;
  for (const key of Object.keys(lightTokens) as McpUiStyleVariableKey[]) {
    variables[key] = lightTokens[key];
  }
  return { variables, css: { fonts: HOST_FONT_CSS } };
}

/**
 * NGOPilot always resolves to the light theme, regardless of OS preference or
 * a previously stored `theme: dark` setting.
 */
export function getResolvedTheme(): 'light' {
  return 'light';
}

/**
 * Apply the light theme tokens to the document root as CSS custom properties.
 * The optional argument is accepted for compatibility and ignored.
 */
export function applyThemeTokens(_theme?: 'light' | 'dark'): void {
  const root = document.documentElement;
  root.classList.remove('dark');
  root.style.colorScheme = 'light';
  for (const [key, value] of Object.entries(lightTokens)) {
    root.style.setProperty(key, value);
  }
}
