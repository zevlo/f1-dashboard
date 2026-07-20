// Environment variables injected at build time by Vite.
// See .env.example for documentation.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
const WS_URL = import.meta.env.VITE_WS_URL ?? ''

if (!API_BASE_URL || !WS_URL) {
  // Don't throw — surface the issue in the UI instead. Vite replaces these at
  // build time, so missing values mean the deploy pipeline didn't inject them.
  console.warn(
    '[config] Missing VITE_API_BASE_URL or VITE_WS_URL. The dashboard will not be able to fetch data.',
  )
}

export const config = {
  apiBaseUrl: API_BASE_URL,
  wsUrl: WS_URL,
  // Maximum number of comparison drivers a user can layer on the lap chart
  // alongside the focused driver. Tuned for readability of the chart.
  maxComparisonDrivers: 2,
} as const
