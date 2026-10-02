import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { workflowAgents, workflowCommands, workflowSkills } from './interactive-project-config.mjs'

const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value
export const ioDigest = value => {
  if (typeof value === 'string') { try { value = JSON.parse(value) } catch { /* plain text */ } }
  return crypto.createHash('sha256').update(JSON.stringify(canonical(value)) ?? 'null').digest('hex')
}
export const hasExplicitTraceConsent = text => /^TRACE — I consent to hosted capture of this fresh interactive session(?:[,.]|$)/u.test(String(text).split(/\r?\n/, 1)[0].trim())
const sessionOf = event => event.properties?.sessionID || event.properties?.info?.sessionID || event.properties?.part?.sessionID || event.properties?.info?.id
const cloneSpan = (span, attributes) => Object.assign(Object.create(span), { attributes, spanContext: () => span.spanContext() })
export function createInteractiveRouting({ recorder, projects, credentials, store, client, notify = async () => {},
  deliver, flush, shutdown, bufferLimitBytes = 16 * 1024 * 1024, source = {}, host }) {
  const states = new Map(), parents = new Map(), active = new Map()
  let tail = Promise.resolve(), disposed = false
  const serial = action => {
    const promise = tail.then(action)
    tail = promise.catch(() => {})
    return promise
  }
  function owner(session) {
    const seen = new Set()
    while (parents.has(session)) {
      if (seen.has(session)) throw new Error('Cyclic session ownership')
      seen.add(session); session = parents.get(session)
    }
    return session
  }
  function stateFor(session) {
    const id = owner(session)
    if (!states.has(id)) {
      const saved = store.load(id)
      const consented = saved?.consented === true
      if (consented && saved?.projectId && saved.projectId !== projects[saved.destination]?.projectId) throw new Error('Persisted destination differs from configured project; use a fresh session')
      states.set(id, { id, consented, consentedAt: consented ? saved?.consentedAt || null : null,
        destination: consented ? saved?.destination || null : null, projectId: consented ? saved?.projectId || null : null,
        bindingSource: consented ? saved?.bindingSource || null : null, error: consented ? saved?.error || null : null,
        checkedHistory: consented && Boolean(saved), ticket: consented ? saved?.ticket || null : null,
        loadedSkills: consented ? saved?.loadedSkills || {} : {},
        completedMessages: new Set(consented ? saved?.completedMessages || [] : []),
        completedTools: new Set(consented ? saved?.completedTools || [] : []),
        held: [], heldBytes: 0, receipts: saved?.receipts || [], pendingReceipt: [], deliveryErrors: 0 })
    }
    return states.get(id)
  }
  function save(state) {
    store.save(state.id, { consented: state.consented, consentedAt: state.consentedAt,
      destination: state.destination, projectId: state.projectId, bindingSource: state.bindingSource,
      error: state.error, ticket: state.ticket, loadedSkills: state.loadedSkills,
      completedMessages: [...state.completedMessages], completedTools: [...state.completedTools], receipts: state.receipts })
  }
  async function hydrate(session) {
    if (!parents.has(session) && client?.session?.get) {
      const response = await client.session.get({ path: { id: session } })
      if (response.error || !response.data) throw new Error('Cannot determine session ancestry; routing is blocked')
      if (response.data.parentID) {
        parents.set(session, response.data.parentID)
        await hydrate(response.data.parentID)
      }
    }
    return stateFor(session)
  }
  async function bind(state, destination, bindingSource) {
    if (!state.consented) throw new Error('Explicit TRACE consent is required before tracing this conversation')
    if (state.error) throw new Error(state.error)
    if (state.destination && state.destination !== destination) throw new Error('This conversation already owns another project. Start a fresh conversation for the new primary workflow')
    try { await credentials.verify(destination) }
    catch (error) {
      state.error = error.message
      save(state)
      throw new Error(state.error)
    }
    if (!state.destination) {
      state.destination = destination; state.projectId = projects[destination].projectId; state.bindingSource = bindingSource
      save(state) // Durable ownership before releasing any provisional span.
      await notify({ sessionID: state.id, destination, projectId: state.projectId, ownership: 'verified', ingestion: 'not_verified' })
      const held = state.held.splice(0); state.heldBytes = 0
      for (const span of held) exportSpan(state, span)
    }
  }
  async function requireFreshSession(state, currentMessageID) {
    if (state.checkedHistory) return
    if (!client?.session?.messages) throw new Error('Session history lookup unavailable; cannot safely accept TRACE consent')
    const response = await client.session.messages({ path: { id: state.id } })
    if (response.error || !Array.isArray(response.data)) throw new Error('Session history lookup failed; TRACE consent refused')
    const oldUsers = response.data.filter(message => message.info.role === 'user' && message.info.id !== currentMessageID)
    if (oldUsers.length) throw new Error('TRACE consent is accepted only as the first user message in a fresh conversation; start a new conversation')
    state.checkedHistory = true
  }
  function exportSpan(state, span) {
    if (!state.consented || state.error) return
    const attributes = { ...span.attributes, 'session.id': state.id,
      'langfuse.trace.name': state.destination === 'generic' ? 'opencode.chat' : `uxd.${state.destination}`,
      'langfuse.trace.tags': ['team:uxd', `component:${state.destination}`],
      'langfuse.observation.metadata.component': state.destination,
      'langfuse.observation.metadata.owner_session_id': state.id,
      'langfuse.observation.metadata.opencode_session_id': span.attributes['session.id'],
      'langfuse.observation.metadata.project_id': state.projectId,
      'langfuse.observation.metadata.binding_source': state.bindingSource,
      ...(state.ticket ? { 'langfuse.observation.metadata.ticket': state.ticket } : {}),
      'langfuse.observation.metadata.loaded_skill_fingerprints': JSON.stringify(state.loadedSkills),
      'langfuse.observation.metadata.capture_scope': 'available_conversation_context_not_wire_prompt',
      ...Object.fromEntries(Object.entries(source).map(([key, value]) => [`langfuse.observation.metadata.${key}`, value])),
    }
    let cost = null
    if (attributes['langfuse.observation.type'] === 'generation') {
      try { cost = JSON.parse(attributes['langfuse.observation.cost_details'])?.total } catch { /* unavailable */ }
      if (!Number.isFinite(cost) || cost < 0) cost = null
      attributes['langfuse.observation.metadata.billing_source'] = cost === null ? 'unavailable' : cost === 0 ? 'opencode-reported-zero-unvalidated' : 'opencode-model-price-card'
    }
    const safe = credentials.redact(attributes)
    const context = span.spanContext()
    const entry = { id: context.spanId, traceId: context.traceId, parentId: span.parentSpanContext?.spanId || null,
      name: span.name, type: attributes['langfuse.observation.type'], model: attributes['langfuse.observation.model.name'] || null,
      startTime: span.startTime, endTime: span.endTime, cost, usage: attributes['langfuse.observation.usage_details'] || null,
      inputSHA256: ioDigest(safe['langfuse.observation.input']), outputSHA256: ioDigest(safe['langfuse.observation.output']) }
    state.pendingReceipt.push(entry)
    try { deliver(state.destination, cloneSpan(span, safe)) }
    catch { state.deliveryErrors++; state.error = 'Destination exporter failed; no fallback or model replay permitted' }
  }
  function onEnd(span) {
    const session = span.attributes['session.id']
    if (!session) return // Never export an unclassified observation.
    const state = stateFor(session)
    if (!state.consented) return
    if (state.destination && !state.error) return exportSpan(state, span)
    // Snapshot without mutating or reopening the ended recorder observation.
    const snapshot = cloneSpan(span, structuredClone(span.attributes))
    state.held.push(snapshot)
    state.heldBytes += Buffer.byteLength(JSON.stringify(snapshot.attributes)) + 512
    if (state.heldBytes > bufferLimitBytes || state.held.length > 10000) {
      state.error = 'Provisional tracing buffer limit exceeded. Stop and start a fresh selected workflow conversation'
      state.held = []; state.heldBytes = 0; save(state)
    }
  }
  async function finalize(session) {
    const state = stateFor(session)
    if (!state.consented) { state.held = []; state.heldBytes = 0; return }
    if (owner(session) !== session) return // A child becoming idle cannot finalize its owner.
    if (!state.destination && !state.error) await bind(state, 'generic', 'ordinary-turn-completed')
    let delivery = null
    if (state.destination && !state.error) {
      try { delivery = await flush(state.destination) }
      catch { state.deliveryErrors++; state.error = 'Destination flush failed; remote ingestion is unverified' }
      if (delivery && (delivery.batches_failed > 0 || delivery.pending_batches > 0 || delivery.journal_write_failed)) state.error = 'Export delivery is incomplete or failed; independently verify the receipt before further work'
    }
    const expected = state.pendingReceipt.splice(0)
    const base = host && state.projectId ? `${host}/project/${encodeURIComponent(state.projectId)}` : null
    state.receipts.push({ recordedAt: new Date().toISOString(), destination: state.destination,
      projectId: state.projectId, expected,
      sessionURL: base ? `${base}/sessions/${encodeURIComponent(state.id)}` : null,
      traceURLs: base ? [...new Set(expected.map(e => e.traceId))].map(id => `${base}/traces/${id}`) : [],
      withheldObservations: state.held.length, exportStatus: state.error ? 'blocked_or_failed' : 'flush_completed',
      delivery, error: state.error, remoteIngestion: 'not_verified' })
    state.held = []; state.heldBytes = 0
    save(state)
  }
  const hooks = {
    'command.execute.before': (input, output) => serial(async () => {
      if (!input.sessionID) return
      const state = await hydrate(input.sessionID)
      if (!state.consented) return
      const destination = workflowCommands[input.command]
      if (destination) await bind(state, destination, 'interactive-command')
      await recorder['command.execute.before']?.(input, output)
    }),
    'chat.message': (input, output) => serial(async () => {
      if (disposed) throw new Error('Tracing instance disposed; restart the backend')
      const state = await hydrate(input.sessionID)
      const text = (output.parts || []).filter(p => p.type === 'text').map(p => p.text).join('\n')
      if (!state.consented) {
        if (output.message?.role !== 'user' || !hasExplicitTraceConsent(text)) return
        await requireFreshSession(state, output.message.id)
        state.consented = true
        state.consentedAt = new Date().toISOString()
        save(state)
      }
      if (!state.ticket) {
        const tickets = [...new Set(text.match(/\b[A-Z][A-Z0-9_]*-\d+\b/g) || [])]
        if (tickets.length === 1) state.ticket = tickets[0] // Metadata only, never a routing signal.
      }
      const agent = output.message.agent || input.agent
      const destination = workflowAgents[agent]
      if (destination && owner(input.sessionID) === input.sessionID) await bind(state, destination, 'selected-primary-agent')
      if (state.destination) await credentials.verify(state.destination)
      if (state.error) throw new Error(state.error)
      active.set(input.sessionID, output.message.id)
      await recorder['chat.message']?.({ ...input, agent, messageID: output.message.id, model: output.message.model || input.model }, output)
    }),
    'chat.params': (input, output) => serial(async () => {
      const state = await hydrate(input.sessionID)
      if (!state.consented) return
      const destination = workflowAgents[input.message?.agent] || workflowAgents[input.agent]
      if (destination && owner(input.sessionID) === input.sessionID) await bind(state, destination, 'pre-model-agent')
      if (state.error) throw new Error(state.error)
      if (state.destination) await credentials.verify(state.destination)
      await recorder['chat.params']?.(input, output)
    }),
    'tool.execute.before': (input, output) => serial(async () => {
      const state = await hydrate(input.sessionID)
      if (!state.consented) return
      if (state.error) throw new Error(state.error)
      if (state.destination === 'evaluator' && input.tool === 'bash') {
        const command = output.args?.command || ''
        if (command.includes('--approve-estimate') || command.includes('langfuse-trace-pipeline.py') && !command.includes('interactive-eval-estimate.mjs')) throw new Error('Interactive evaluator supports only the reviewed estimate wrapper. Paid/direct execution needs separate integration and approval')
      }
      const destination = input.tool === 'skill' ? workflowSkills[output.args?.name] : null
      if (destination && owner(input.sessionID) === input.sessionID) await bind(state, destination, 'actual-skill-tool')
      if (state.destination) await credentials.verify(state.destination)
      await recorder['tool.execute.before']?.(input, output)
    }),
    'tool.execute.after': (input, output) => serial(async () => {
      if (!input.sessionID || !stateFor(input.sessionID).consented) return
      if (input.tool === 'skill' && workflowSkills[output.metadata?.name] && path.isAbsolute(output.metadata?.dir || '')) {
        const state = stateFor(input.sessionID)
        try {
          const content = fs.readFileSync(path.join(output.metadata.dir, 'SKILL.md'))
          state.loadedSkills[output.metadata.name] = crypto.createHash('sha256').update(content).digest('hex')
        } catch { state.loadedSkills[output.metadata.name] = 'unavailable' }
      }
      await recorder['tool.execute.after']?.(input, output)
    }),
    // No evaluator credentials/parent bridge are injected into ordinary shells.
    'shell.env': (input, output) => serial(async () => {
      if (input.sessionID) {
        const state = await hydrate(input.sessionID)
        if (!state.consented) return
        if (state.error) throw new Error(state.error)
        output.env.UXD_INTERACTIVE_SESSION_ID = state.id
        output.env.UXD_INTERACTIVE_COMPONENT = state.destination || 'provisional'
      }
    }),
    event({ event }) {
      // Ancestry must be recorded synchronously: OpenCode does not await bus hooks.
      if (['session.created', 'session.updated'].includes(event.type) && event.properties?.info?.parentID) parents.set(event.properties.info.id, event.properties.info.parentID)
      return serial(async () => {
        const session = sessionOf(event)
        if (!session) return recorder.event?.({ event })
        const state = stateFor(session)
        if (!state.consented) return
        const info = event.properties?.info, part = event.properties?.part
        if (event.type === 'message.updated' && info?.role === 'assistant' && state.completedMessages.has(info.id)) return
        if (event.type === 'session.next.step.started' && state.completedMessages.has(event.properties.assistantMessageID)) return
        if (event.type === 'message.part.updated' && part?.type === 'tool' && state.completedTools.has(part.callID)) return
        if (event.type === 'session.idle' && active.has(session)) {
          // Reconcile only this turn, never replay historical generations.
          await new Promise(resolve => setTimeout(resolve, 100))
          const messages = await client.session.messages({ path: { id: session } })
          if (messages.error || !Array.isArray(messages.data)) throw new Error('Idle reconciliation unavailable')
          for (const message of messages.data) {
            const m = message.info
            if (m.role !== 'assistant' || m.parentID !== active.get(session) || !m.time?.completed || state.completedMessages.has(m.id)) continue
            for (const part of message.parts || []) await recorder.event?.({ event: { type: 'message.part.updated', properties: { part } } })
            await recorder.event?.({ event: { type: 'message.updated', properties: { info: m } } })
            state.completedMessages.add(m.id)
          }
        }
        await recorder.event?.({ event })
        if (event.type === 'message.updated' && info?.role === 'assistant' && info.time?.completed) state.completedMessages.add(info.id)
        if (part?.type === 'tool' && ['completed', 'error'].includes(part.state?.status)) state.completedTools.add(part.callID)
        if (event.type === 'session.idle') { await finalize(session); active.delete(session) }
      }).catch(async () => {
        const session = sessionOf(event)
        if (session) {
          const state = stateFor(session); state.error = 'Interactive tracing event failed; stop and inspect the local receipt'; save(state)
          await notify({ sessionID: state.id, error: state.error, ingestion: 'not_verified' })
        }
      })
    },
    dispose: () => serial(async () => {
      if (disposed) return
      disposed = true
      await recorder.dispose?.()
      // Disposal cannot guess a provisional workflow's ownership.
      for (const state of states.values()) {
        if (!state.consented) continue
        if (!state.destination && state.held.length) state.error ||= 'Instance disposed before ownership was established; provisional observations withheld'
        await finalize(state.id)
      }
      await shutdown()
    }),
  }
  return { hooks, onEnd, active, wait: () => tail, snapshot: session => stateFor(session) }
}
