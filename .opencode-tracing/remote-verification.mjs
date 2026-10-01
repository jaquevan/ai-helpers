import { spawnSync } from 'node:child_process'

export function compareObservations(receipt, observations) {
  const rows = [...new Map(observations.map(o => [o.id, o])).values()]
  const expected = receipt.expected_observations
  const sessionIDs = expected && new Set(expected.map(o => o.id))
  const owned = sessionIDs ? rows.filter(o => sessionIDs.has(o.id)) : rows
  const generations = owned.filter(o => o.name === 'opencode.generation')
  const counts = {
    roots: rows.filter(o => o.isRootObservation).length,
    generations: generations.length,
    tools: owned.filter(o => o.type === 'TOOL').length,
    user_turns: owned.filter(o => o.name === 'opencode.turn').length,
  }
  const wanted = { roots: 1, generations: receipt.generations, tools: receipt.tool_calls, user_turns: receipt.user_turns }
  const discrepancies = []
  if (![receipt.generations, receipt.tool_calls, receipt.user_turns].every(Number.isInteger)) discrepancies.push('Local receipt counters are not finalized')
  for (const [field, count] of Object.entries(wanted)) if (Number.isInteger(count) && counts[field] !== count) discrepancies.push(`${field}: expected ${count}, observed ${counts[field]}`)
  const present = new Set(rows.map(o => o.id))
  const missing = expected?.filter(o => !present.has(o.id)) || []
  if (missing.length) discrepancies.push(`${missing.length} expected observation IDs missing`)
  if (rows.some(o => o.traceId !== receipt.trace_id)) discrepancies.push('Unexpected trace ID in API response')
  // Langfuse may apply its own catalog price to an unpriced generation. Compare
  // only explicitly sourced OpenCode costs; inferred prices are not local facts.
  const cost = generations.filter(o => o.metadata?.billing_source === 'opencode-model-price-card').reduce((sum, o) => sum + (typeof o.costDetails?.total === 'number' ? o.costDetails.total : 0), 0)
  if (typeof receipt.known_session_cost_usd === 'number' && Math.abs(cost - receipt.known_session_cost_usd) > 1e-8) discrepancies.push('Known generation cost subtotal differs from local receipt')
  return {
    run_id: receipt.run_id, trace_id: receipt.trace_id,
    status: discrepancies.length ? 'partial' : 'verified',
    verification_scope: expected ? 'session_observation_ids_counts_and_known_cost' : 'legacy_counts_and_known_cost_only',
    expected: wanted, observed: counts, missing_observations: missing,
    local_known_cost_usd: receipt.known_session_cost_usd ?? null,
    remote_known_cost_usd: cost, discrepancies,
    // Currency remains the supplied price-card estimate, never an invoice.
    verified_at: new Date().toISOString(),
  }
}

export function fetchObservations(receipt, credentials, request = spawnSync) {
  if (!/^[a-f0-9]{32}$/.test(receipt.trace_id || '')) throw new Error('Receipt has no valid trace ID.')
  const host = (credentials.LANGFUSE_BASE_URL || credentials.LANGFUSE_HOST || '').replace(/\/$/, '')
  if (!host.startsWith('https://')) throw new Error('Expected an HTTPS Langfuse host.')
  const auth = Buffer.from(`${credentials.LANGFUSE_PUBLIC_KEY}:${credentials.LANGFUSE_SECRET_KEY}`).toString('base64')
  const query = new URLSearchParams({ traceId: receipt.trace_id, fields: 'basic,usage,metadata', limit: '1000' })
  const rows = [], cursors = new Set()
  let cursor
  do {
    if (cursor) query.set('cursor', cursor)
    const response = request('curl', ['--config', '-', '--fail', '--silent', '--show-error', '--max-time', '15', `${host}/api/public/v2/observations?${query}`], {
      input: `header = "Authorization: Basic ${auth}"\n`, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024,
    })
    if (response.status !== 0) throw new Error('Read-only remote verification failed (network or credentials).')
    let data
    try { data = JSON.parse(response.stdout) } catch { throw new Error('Remote verification returned invalid JSON.') }
    if (!Array.isArray(data.data)) throw new Error('Remote verification returned an unexpected response.')
    rows.push(...data.data)
    cursor = data.meta?.cursor
    if (cursor && cursors.has(cursor)) throw new Error('Remote verification returned a repeated pagination cursor.')
    if (cursor) cursors.add(cursor)
  } while (cursor)
  return rows
}

export async function verifyRemote(receipt, credentials, { attempts = 3, fetch = fetchObservations, pause = ms => new Promise(r => setTimeout(r, ms)) } = {}) {
  let result
  for (let i = 0; i < attempts; i++) {
    try { result = compareObservations(receipt, fetch(receipt, credentials)) }
    catch (error) { return { run_id: receipt.run_id, trace_id: receipt.trace_id, status: 'unavailable', reason: error.message, verified_at: new Date().toISOString() } }
    if (result.status === 'verified') return result
    if (i + 1 < attempts) await pause(2000)
  }
  return result
}
