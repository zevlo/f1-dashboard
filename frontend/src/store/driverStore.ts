import { create } from 'zustand'

// Focused driver + comparison set. Driver click mutates only this store —
// no network. The telemetry panel + chart subscribe to selectedDriverNumber;
// the chart layers comparisonDrivers on top.
//
// Click rules:
//   plain click  → set selectedDriverNumber (or clear if same)
//   shift-click  → toggle into/out of comparisonDrivers

import { config } from '../config'

interface DriverState {
  selectedDriverNumber: number | null
  comparisonDrivers: number[]
  select: (driverNumber: number) => void
  toggleComparison: (driverNumber: number) => void
  clear: () => void
}

export const useDriverStore = create<DriverState>((set) => ({
  selectedDriverNumber: null,
  comparisonDrivers: [],
  select: (driverNumber) =>
    set((s) => ({
      selectedDriverNumber: s.selectedDriverNumber === driverNumber ? null : driverNumber,
    })),
  toggleComparison: (driverNumber) =>
    set((s) => {
      if (s.comparisonDrivers.includes(driverNumber)) {
        return { comparisonDrivers: s.comparisonDrivers.filter((d) => d !== driverNumber) }
      }
      if (s.comparisonDrivers.length >= config.maxComparisonDrivers) return s
      return { comparisonDrivers: [...s.comparisonDrivers, driverNumber] }
    }),
  clear: () => set({ selectedDriverNumber: null, comparisonDrivers: [] }),
}))
