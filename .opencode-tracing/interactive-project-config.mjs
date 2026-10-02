import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import crypto from 'node:crypto'
import { canonicalHost, canonicalProjects, readAssignments, hashUser } from './runtime.mjs'
import { redactor } from './plugins/session-root-core.mjs'

export const components = ['creator', 'consistency', 'evaluator', 'generic']
export const workflowAgents = { 'uxd-creator': 'creator', 'uxd-consistency': 'consistency', 'uxd-evaluator': 'evaluator' }
export const workflowSkills = { 'uxd-prototype-create': 'creator', 'uxd-consistency-check': 'consistency', 'uxd-prototype-evaluate': 'evaluator' }
export const workflowCommands = { 'uxd-create': 'creator', 'uxd-consistency': 'consistency', 'uxd-evaluate': 'evaluator' }
export function privateFile(file) {
  const stat = fs.lstatSync(file)
  if (!stat.isFile() || stat.isSymbolicLink() || (stat.mode & 0o777) !== 0o600 || stat.uid !== os.userInfo().uid) throw new Error('Routing/credential/state files must be owner-owned regular nonsymlink files with mode 600')
  return file
}
export function privateDirectory(dir) {
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 })
  const stat = fs.lstatSync(dir)
  if (!stat.isDirectory() || stat.isSymbolicLink() || (stat.mode & 0o777) !== 0o700 || stat.uid !== os.userInfo().uid) throw new Error('Routing state directory must be owner-owned, nonsymlink and mode 700')
}
export function loadRoutingConfig(file) {
  const config = JSON.parse(fs.readFileSync(privateFile(file), 'utf8'))
  if (config.version !== 1 || config.host !== canonicalHost || !path.isAbsolute(config.stateDirectory || '')) throw new Error('Unsupported routing config version, host or state directory')
  if (Object.keys(config).some(key => !['version', 'host', 'stateDirectory', 'projects', 'bufferLimitBytes'].includes(key))) throw new Error('Unknown interactive routing config field')
  if (Object.keys(config.projects || {}).sort().join(',') !== components.slice().sort().join(',')) throw new Error('Configure exactly creator, consistency, evaluator and generic destinations')
  for (const component of components) {
    const project = config.projects[component]
    if (!project || !path.isAbsolute(project.credentialFile || '') || !/^[a-zA-Z0-9_-]+$/.test(project.projectId || '') || !['env', 'upstream-json'].includes(project.format)) throw new Error('Invalid destination declaration')
    if (Object.keys(project).some(key => !['credentialFile', 'projectId', 'format'].includes(key))) throw new Error('Unknown destination field')
    if (component !== 'generic' && project.projectId !== canonicalProjects[component]) throw new Error('Wrong canonical component project ID')
  }
  if (config.bufferLimitBytes !== undefined && (!Number.isInteger(config.bufferLimitBytes) || config.bufferLimitBytes < 1024 || config.bufferLimitBytes > 64 * 1024 * 1024)) throw new Error('Invalid routing buffer limit')
  return config
}
export function credentialManager(config, { request = fetch, now = Date.now } = {}) {
  const cache = new Map()
  const secrets = { ...process.env }
  let userID = hashUser(os.userInfo().username)
  function load(component) {
    try {
      const destination = config.projects[component]
      const file = privateFile(destination.credentialFile)
      const data = destination.format === 'env' ? readAssignments(file) : JSON.parse(fs.readFileSync(file, 'utf8'))
      const c = destination.format === 'env' ? data : {
        LANGFUSE_BASE_URL: data.baseUrl, LANGFUSE_PUBLIC_KEY: data.publicKey,
        LANGFUSE_SECRET_KEY: data.secretKey, LANGFUSE_ENVIRONMENT: data.environment, LANGFUSE_USER_ID: data.userId,
      }
      if ((c.LANGFUSE_BASE_URL || c.LANGFUSE_HOST || '').replace(/\/$/, '') !== config.host || !c.LANGFUSE_PUBLIC_KEY || !c.LANGFUSE_SECRET_KEY || c.LANGFUSE_PROJECT_ID && c.LANGFUSE_PROJECT_ID !== destination.projectId) throw new Error()
      secrets[`${component}_KEY`] = c.LANGFUSE_PUBLIC_KEY
      secrets[`${component}_SECRET`] = c.LANGFUSE_SECRET_KEY
      if (c.OPENAI_API_KEY) secrets[`${component}_OPENAI_KEY`] = c.OPENAI_API_KEY
      if (component === 'generic' && c.LANGFUSE_USER_ID && c.LANGFUSE_USER_ID !== 'anonymous') userID = hashUser(c.LANGFUSE_USER_ID)
      return { ...c, LANGFUSE_BASE_URL: config.host, LANGFUSE_PROJECT_ID: destination.projectId }
    } catch { throw new Error(`Cannot securely load ${component} destination credentials; no fallback permitted`) }
  }
  // Redaction covers every readable project key, not only the selected project.
  for (const component of components) { try { load(component) } catch { /* binding will fail closed for this destination */ } }
  return {
    redact: value => redactor(secrets)(value),
    async verify(component) {
      const c = load(component)
      const fingerprint = crypto.createHash('sha256').update(JSON.stringify(c)).digest('hex')
      const previous = cache.get(component)
      if (previous?.fingerprint === fingerprint && previous.expires > now()) return previous.promise
      const promise = (async () => {
        try {
          const response = await request(`${config.host}/api/public/projects`, {
            method: 'GET', headers: { Authorization: `Basic ${Buffer.from(`${c.LANGFUSE_PUBLIC_KEY}:${c.LANGFUSE_SECRET_KEY}`).toString('base64')}` }, signal: AbortSignal.timeout(15000), redirect: 'error',
          })
          if (!response.ok) throw new Error()
          const data = (await response.json()).data
          if (!Array.isArray(data) || data.length !== 1 || data[0].id !== config.projects[component].projectId) throw new Error()
          return Object.freeze({ ...c, LANGFUSE_USER_ID: userID })
        } catch { cache.delete(component); throw new Error(`Project ownership verification failed for ${component}; no workflow fallback permitted`) }
      })()
      cache.set(component, { fingerprint, expires: now() + 60000, promise })
      return promise
    },
  }
}
export function bindingStore(directory, workspace) {
  const workspaceID = crypto.createHash('sha256').update(workspace).digest('hex').slice(0, 24)
  const dir = path.join(directory, workspaceID)
  privateDirectory(dir)
  const fileFor = session => path.join(dir, `${crypto.createHash('sha256').update(session).digest('hex')}.json`)
  return {
    directory: dir,
    load(session) {
      const file = fileFor(session)
      if (!fs.existsSync(file)) return null
      try {
        const state = JSON.parse(fs.readFileSync(privateFile(file), 'utf8'))
        if (state.sessionID !== session || state.version !== 1 || state.destination && !components.includes(state.destination)) throw new Error()
        return state
      } catch { throw new Error('Persisted routing state is invalid; stop rather than guessing ownership') }
    },
    save(session, state) {
      const file = fileFor(session), temporary = `${file}.tmp-${process.pid}`
      // Only routing IDs, summaries and hashes go to disk, never raw I/O or keys.
      const data = JSON.stringify({ ...state, version: 1, sessionID: session }, null, 2)
      const lock = `${file}.lock`
      const fd = fs.openSync(lock, 'wx', 0o600)
      try {
        if (fs.existsSync(file)) {
          const previous = JSON.parse(fs.readFileSync(privateFile(file), 'utf8'))
          if (previous.destination && previous.destination !== state.destination) throw new Error('Concurrent session ownership differs; stop rather than changing destination')
        }
        fs.writeFileSync(temporary, data, { mode: 0o600, flag: 'wx' })
        fs.renameSync(temporary, file)
      } finally { fs.closeSync(fd); fs.unlinkSync(lock) }
    },
  }
}
