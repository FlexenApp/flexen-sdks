import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['test/**/*.test.ts'],
    // Lean on a shared machine: two workers at most.
    maxWorkers: 2,
    testTimeout: 20_000,
  },
})
