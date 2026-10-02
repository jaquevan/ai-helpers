import { ioDigest } from './interactive-routing-core.mjs'

export function compareInteractiveObservations(state, intended, others) {
  const expected = [...new Map(state.receipts.flatMap(r => r.expected || []).map(o => [o.id, o])).values()]
  const rows = new Map(intended.map(o => [o.id, o]))
  const discrepancies = [], expectedIDs = new Set(expected.map(o => o.id))
  for (const e of expected) {
    const row = rows.get(e.id)
    if (!row) { discrepancies.push({ id: e.id, problem: 'missing' }); continue }
    if (row.traceId !== e.traceId || (row.parentObservationId || null) !== e.parentId) discrepancies.push({ id: e.id, problem: 'trace_or_parent_differs' })
    if (row.name !== e.name || String(row.type).toLowerCase() !== e.type) discrepancies.push({ id: e.id, problem: 'name_or_type_differs' })
    if (ioDigest(row.input) !== e.inputSHA256 || ioDigest(row.output) !== e.outputSHA256) discrepancies.push({ id: e.id, problem: 'io_hash_differs' })
    const millis = hr => Math.round(hr[0] * 1000 + hr[1] / 1e6)
    if (Math.abs(Date.parse(row.startTime) - millis(e.startTime)) > 1 || Math.abs(Date.parse(row.endTime) - millis(e.endTime)) > 1) discrepancies.push({ id: e.id, problem: 'timestamps_differ' })
    if (e.type === 'generation') {
      if (row.model !== e.model) discrepancies.push({ id: e.id, problem: 'model_differs' })
      let usage
      try { usage = JSON.parse(e.usage) } catch { usage = {} }
      if (Object.entries(usage).some(([key, value]) => row.usageDetails?.[key] !== value)) discrepancies.push({ id: e.id, problem: 'usage_differs' })
      if (e.cost !== null && (typeof row.costDetails?.total !== 'number' || Math.abs(row.costDetails.total - e.cost) > 1e-8)) discrepancies.push({ id: e.id, problem: 'explicit_cost_differs' })
    }
  }
  for (const [component, observations] of Object.entries(others)) {
    if (observations.some(o => expectedIDs.has(o.id))) discrepancies.push({ project: component, problem: 'expected_observation_in_unintended_project' })
  }
  const foreign = intended.filter(o => !expectedIDs.has(o.id))
  if (foreign.length) discrepancies.push({ problem: 'unexpected_observations_in_owned_traces', count: foreign.length })
  const known = expected.filter(e => e.type === 'generation' && e.cost !== null).reduce((sum, e) => sum + e.cost, 0)
  return { status: expected.length && !discrepancies.length ? 'verified' : 'partial', session_id: state.sessionID,
    destination: state.destination, project_id: state.projectId, observations_expected: expected.length,
    observations_present: expected.filter(e => rows.has(e.id)).length, known_session_cost_usd: known,
    unknown_cost_generations: expected.filter(e => e.type === 'generation' && e.cost === null).length,
    zero_cost_generations_unvalidated: expected.filter(e => e.type === 'generation' && e.cost === 0).length,
    checked_unintended_projects: Object.keys(others), discrepancies,
    scope: 'observation_ids_hierarchy_models_io_hashes_timestamps_usage_explicit_costs_and_project_exclusivity',
    verified_at: new Date().toISOString(), currency_authority: 'opencode_supplied_cost_not_provider_invoice' }
}
