/**
 * Theme tokens — the single source of truth for all MCP semantic token values.
 *
 * Every key in McpUiStyleVariableKey must be present in both lightTokens and
 * darkTokens. The TypeScript compiler enforces this: if the SDK adds a new key,
 * the build breaks until both maps are updated.
 *
 * Values are applied to :root via style.setProperty() before first paint
 * (see renderer.tsx). main.css only registers the variable names for Tailwind
 * class generation — it does NOT define values.
 *
 * These tokens serve two purposes:
 *  1. NGOPilot desktop — applied to :root per resolved theme.
 *  2. MCP apps — encoded as light-dark() in hostContext.styles.variables.
 */
import type {
  McpUiHostStyles,
  McpUiStyleVariableKey,
  McpUiStyles,
} from '@modelcontextprotocol/ext-apps/app-bridge';

type ThemeTokens = Record<McpUiStyleVariableKey, string>;

// Subset of keys that are the same across both themes.
type BaseTokenKey = Extract<
  McpUiStyleVariableKey,
  `--font-${string}` | `--border-radius-${string}` | `--border-width-${string}`
>;

type ColorTokenKey = Exclude<McpUiStyleVariableKey, BaseTokenKey>;

// ---------------------------------------------------------------------------
// Base tokens — shared across light and dark themes
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
  '--border-radius-sm': '4px',
  '--border-radius-md': '8px',
  '--border-radius-lg': '12px',
  '--border-radius-xl': '16px',
  '--border-radius-full': '9999px',

  // Border width
  '--border-width-regular': '1px',
};

// Theme-specific color/shadow tokens only.
type ColorTokens = Pick<ThemeTokens, ColorTokenKey>;

// ---------------------------------------------------------------------------
// Light theme — colors & shadows
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
  '--color-background-warning': '#a8841f',
  '--color-background-disabled': '#efe8da',

  // Text
  '--color-text-primary': '#1d2622',
  '--color-text-secondary': '#7a766b',
  '--color-text-tertiary': '#7a766b',
  '--color-text-inverse': '#fffdf8',
  '--color-text-ghost': '#7a766b',
  '--color-text-info': '#7d3b27',
  '--color-text-danger': '#6b2419',
  '--color-text-success': '#7d3b27',
  '--color-text-warning': '#6b5310',
  '--color-text-disabled': '#969083',

  // Borders
  '--color-border-primary': '#efe8da',
  '--color-border-secondary': '#ddd6c6',
  '--color-border-tertiary': '#969083',
  '--color-border-inverse': '#1d2622',
  '--color-border-ghost': 'transparent',
  '--color-border-info': '#7d3b27',
  '--color-border-danger': '#6b2419',
  '--color-border-success': '#7d3b27',
  '--color-border-warning': '#a8841f',
  '--color-border-disabled': '#efe8da',

  // Rings
  '--color-ring-primary': '#7d3b27',
  '--color-ring-secondary': '#ddd6c6',
  '--color-ring-inverse': '#fffdf8',
  '--color-ring-info': '#7d3b27',
  '--color-ring-danger': '#6b2419',
  '--color-ring-success': '#7d3b27',
  '--color-ring-warning': '#a8841f',

  // Shadows
  '--shadow-hairline': '0 0 0 1px rgba(31, 28, 24, 0.06)',
  '--shadow-sm': '0 1px 2px 0 rgba(31, 28, 24, 0.06)',
  '--shadow-md': '0 1px 0 rgba(20, 18, 14, 0.06), 0 24px 48px -32px rgba(20, 18, 14, 0.18)',
  '--shadow-lg': '0 18px 38px rgba(31, 28, 24, 0.09)',
};

// ---------------------------------------------------------------------------
// Dark theme — colors & shadows
// ---------------------------------------------------------------------------
const darkColorTokens: ColorTokens = {
  // Backgrounds
  '--color-background-primary': '#1d2622',
  '--color-background-secondary': '#1d2622',
  '--color-background-tertiary': '#514e46',
  '--color-background-inverse': '#fffdf8',
  '--color-background-ghost': 'transparent',
  '--color-background-info': '#7d3b27',
  '--color-background-danger': '#6b2419',
  '--color-background-success': '#7d3b27',
  '--color-background-warning': '#a8841f',
  '--color-background-disabled': '#514e46',

  // Text
  '--color-text-primary': '#fffdf8',
  '--color-text-secondary': '#ddd6c6',
  '--color-text-tertiary': '#969083',
  '--color-text-inverse': '#1d2622',
  '--color-text-ghost': '#ddd6c6',
  '--color-text-info': '#f5c8bb',
  '--color-text-danger': '#f5c8bb',
  '--color-text-success': '#d6e0d1',
  '--color-text-warning': '#faf2dc',
  '--color-text-disabled': '#7a766b',

  // Borders
  '--color-border-primary': '#514e46',
  '--color-border-secondary': '#7a766b',
  '--color-border-tertiary': '#7a766b',
  '--color-border-inverse': '#fffdf8',
  '--color-border-ghost': 'transparent',
  '--color-border-info': '#92513d',
  '--color-border-danger': '#92513d',
  '--color-border-success': '#7d3b27',
  '--color-border-warning': '#a8841f',
  '--color-border-disabled': '#514e46',

  // Rings
  '--color-ring-primary': '#92513d',
  '--color-ring-secondary': '#7a766b',
  '--color-ring-inverse': '#1d2622',
  '--color-ring-info': '#92513d',
  '--color-ring-danger': '#92513d',
  '--color-ring-success': '#7d3b27',
  '--color-ring-warning': '#a8841f',

  // Shadows
  '--shadow-hairline': '0 0 0 1px rgba(252, 250, 243, 0.08)',
  '--shadow-sm': '0 1px 2px 0 rgba(14, 12, 10, 0.3)',
  '--shadow-md': '0 1px 0 rgba(252, 250, 243, 0.05), 0 24px 48px -32px rgba(14, 12, 10, 0.72)',
  '--shadow-lg': '0 18px 38px rgba(14, 12, 10, 0.54)',
};

// ---------------------------------------------------------------------------
// Merged token maps — used by applyThemeTokens() and buildMcpHostStyles()
// ---------------------------------------------------------------------------
export const lightTokens: ThemeTokens = { ...baseTokens, ...lightColorTokens };
export const darkTokens: ThemeTokens = { ...baseTokens, ...darkColorTokens };

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
 * Build the McpUiHostStyles object for MCP apps.
 * Color keys use light-dark() so a single payload works for both themes.
 * Non-color keys (fonts, radii, shadows) use plain values from baseTokens
 * (or light as the default when values differ, e.g. shadows).
 * css.fonts provides @font-face rules so sandboxed apps can load host fonts.
 */
export function buildMcpHostStyles(): McpUiHostStyles {
  const variables: McpUiStyles = {} as McpUiStyles;
  for (const key of Object.keys(lightTokens) as McpUiStyleVariableKey[]) {
    const light = lightTokens[key];
    const dark = darkTokens[key];
    if (key.startsWith('--color-')) {
      variables[key] = `light-dark(${light}, ${dark})`;
    } else {
      variables[key] = light;
    }
  }
  return { variables, css: { fonts: HOST_FONT_CSS } };
}

/**
 * Resolve the current theme from localStorage / system preference.
 */
export function getResolvedTheme(): 'light' | 'dark' {
  const useSystem = localStorage.getItem('use_system_theme') !== 'false';
  if (useSystem) {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return localStorage.getItem('theme') === 'dark' ? 'dark' : 'light';
}

/**
 * Apply theme tokens to the document root as CSS custom properties.
 * When called without an argument, resolves the theme from localStorage.
 */
export function applyThemeTokens(theme?: 'light' | 'dark'): void {
  const resolved = theme ?? getResolvedTheme();
  const tokens = resolved === 'dark' ? darkTokens : lightTokens;
  const root = document.documentElement;
  for (const [key, value] of Object.entries(tokens)) {
    root.style.setProperty(key, value);
  }
}
