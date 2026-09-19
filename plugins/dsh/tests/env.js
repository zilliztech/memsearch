/**
 * Run a test body with ambient MemSearch/DSH command routing masked.
 *
 * Every override is restored after the body settles. A null value removes the
 * variable so developer profile settings cannot launch real background tools.
 */
const DEFAULT_ISOLATED_ENV = {
  DSH_CLI: null,
  MEMSEARCH_DSH_COMMAND_JSON: null,
  MEMSEARCH_CMD: null,
  MEMSEARCH_DIR: null,
  MEMSEARCH_PYTHON: null,
}

let envBodyActive = false

/**
 * @param {Record<string, string | null>} overrides
 * @param {() => unknown} fn
 * @returns {Promise<unknown>}
 */
export async function withIsolatedEnv(overrides, fn) {
  if (envBodyActive) throw new Error('withIsolatedEnv overlap')
  envBodyActive = true

  const effective = { ...DEFAULT_ISOLATED_ENV, ...overrides }
  const saved = {}
  try {
    for (const [key, value] of Object.entries(effective)) {
      saved[key] = process.env[key]
      if (value === null || value === undefined) delete process.env[key]
      else process.env[key] = value
    }
    return await fn()
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key]
      else process.env[key] = value
    }
    envBodyActive = false
  }
}
