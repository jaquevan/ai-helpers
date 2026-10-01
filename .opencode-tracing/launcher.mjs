import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import crypto from 'node:crypto'
import { spawnSync, spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { verifyRemote } from './remote-verification.mjs'
import { buildPlan, validateRuntime, nestedSession, readAssignments, hashUser, traceURL, canonicalProjects, canonicalHost } from './runtime.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const fail = (message) => { console.error(message); process.exitCode = 2 }

async function main() {
  validateRuntime(process.versions.node)
  const plan = buildPlan(process.argv.slice(2), root)
  if (plan.dryRun) {
    console.log(JSON.stringify(plan, null, 2))
    return
  }
  if (!plan.verify && (nestedSession(process.env) || !process.stdin.isTTY || !process.stdout.isTTY)) {
    throw new Error('Run trace-in-langfuse from a plain Terminal shell, never from inside OpenCode or an assistant tool. No session started. --dry-run remains available here.')
  }
  // Check ancestry using executable names only, never command arguments.
  if (!plan.verify) {
    let pid = process.ppid
    for (let depth = 0; pid > 1 && depth < 16; depth++) {
      const row = spawnSync('ps', ['-p', String(pid), '-o', 'ppid=', '-o', 'comm='], { encoding: 'utf8' }).stdout?.trim()
      if (!row) break
      const match = row.match(/^(\d+)\s+(.+)$/)
      if (!match) break
      if (/opencode/i.test(path.basename(match[2]))) throw new Error('Nested OpenCode launch refused. Open a plain terminal and run the launcher there.')
      pid = Number(match[1])
    }
    const version = spawnSync('opencode', ['--version'], { encoding: 'utf8' })
    if (version.status !== 0 || version.stdout.trim() !== '1.18.31') throw new Error('This runtime is tested with OpenCode 1.18.31. Install that version before tracing; revalidate hooks before upgrading.')
    const help = spawnSync('opencode', ['run', '--help'], { encoding: 'utf8' })
    if (help.error || help.status !== 0) throw new Error('Unable to inspect OpenCode run options. Try opencode run --help in this terminal; no session started.')
    // OpenCode 1.18.31 writes successful help output to stderr.
    const helpText = `${help.stdout || ''}\n${help.stderr || ''}`
    if (!helpText.includes('--command')) throw new Error('Installed OpenCode lacks run --command; no session started.')
    if (!fs.existsSync(path.join(root, '.opencode-tracing/node_modules/@langfuse/otel'))) throw new Error(`Install tracing dependencies: npm ci --prefix "${root}/.opencode-tracing"`)
    if (plan.component === 'evaluator') {
      const check = spawnSync(path.join(root, '.venv/bin/python'), ['-c', 'import langfuse; from importlib.metadata import version; assert version("langfuse") == "4.15.6"'], { encoding: 'utf8' })
      if (check.status !== 0) throw new Error('Evaluator needs the fork-root .venv with Langfuse 4.15.6. Install .opencode-tracing/requirements.txt; revalidate the bridge before upgrading.')
    }
  }
  const credentialFile = path.join(os.homedir(), '.config/opencode/langfuse', `${plan.component}.env`)
  const credentials = readAssignments(credentialFile)
  const host = (credentials.LANGFUSE_BASE_URL || credentials.LANGFUSE_HOST || '').replace(/\/$/, '')
  for (const field of ['LANGFUSE_PROJECT_ID', 'LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY']) {
    if (!credentials[field]) throw new Error(`Missing ${field} in ${plan.component}.env`)
  }
  if (!/^https:\/\/[^\s]+$/.test(host)) throw new Error('LANGFUSE_BASE_URL must be an HTTPS URL.')
  if (host === canonicalHost && credentials.LANGFUSE_PROJECT_ID !== canonicalProjects[plan.component]) throw new Error(`Wrong project for ${plan.component} on the UXD host. Expected ${canonicalProjects[plan.component]}; check that component’s env file.`)
  // curl receives Basic auth over stdin; keys never appear in argv or output.
  const auth = Buffer.from(`${credentials.LANGFUSE_PUBLIC_KEY}:${credentials.LANGFUSE_SECRET_KEY}`).toString('base64')
  const response = spawnSync('curl', ['--config', '-', '--fail', '--silent', '--show-error', '--max-time', '30', `${host}/api/public/projects`], {
    input: `header = "Authorization: Basic ${auth}"\n`, encoding: 'utf8',
  })
  if (response.status !== 0) throw new Error(`${plan.component} project verification failed (network or credentials). No fallback to another component and no session started.`)
  let projects
  try { projects = JSON.parse(response.stdout).data } catch { throw new Error('Project verification returned invalid JSON.') }
  if (!projects?.some(p => p.id === credentials.LANGFUSE_PROJECT_ID)) throw new Error('Credential project ID does not match the key pair; no session started.')
  if (plan.verify) { console.log(`Verified ${plan.component} project ${credentials.LANGFUSE_PROJECT_ID}; no trace sent.`); return }
  if (plan.component === 'evaluator' && !credentials.OPENAI_API_KEY) throw new Error('Missing OPENAI_API_KEY in evaluator.env.')
  let tty
  try { tty = fs.openSync('/dev/tty', 'r+') } catch { throw new Error('Cannot open an interactive terminal. Run this command in Terminal, outside OpenCode.') }
  fs.writeSync(tty, `\nThis run sends full OpenCode session content to ${host}, project ${credentials.LANGFUSE_PROJECT_ID}.\nIncludes user/assistant text, provider-exposed reasoning and tool I/O (including file contents), with best-effort secret redaction. Use only content approved for this project.\nWorkspace access: ${plan.workspace}\nOpenCode may incur model cost. Evaluator mode: ${plan.approveEstimate ? 'separately approved paid execution' : 'estimate-only; no paid evaluator phases'}.\nType TRACE here to consent to this run (not as a shell command): `)
  let consent = ''
  const byte = Buffer.alloc(1)
  while (fs.readSync(tty, byte, 0, 1, null)) {
    if (byte[0] === 10) break
    consent += byte.toString()
    if (consent.length > 100) break
  }
  fs.closeSync(tty)
  if (consent.replace(/\r$/, '') !== 'TRACE') throw new Error('Tracing cancelled; no OpenCode session started.')

  const runID = `${plan.component}-${new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z')}-${crypto.randomBytes(3).toString('hex')}`
  const runDir = path.join(root, 'tmp/traced-sessions', runID)
  fs.mkdirSync(runDir, { recursive: true, mode: 0o700 })
  const receipt = path.join(runDir, 'receipt.json')
  const pipelineResult = path.join(runDir, 'pipeline-result.json')
  const config = {
    $schema: 'https://opencode.ai/config.json',
    skills: { paths: [path.join(root, 'plugins/uxd-workshop/skills'), path.join(root, 'plugins/uxd-prototype/skills')] },
    plugin: [path.join(root, '.opencode-tracing/plugins/langfuse-session-root.mjs')],
    share: 'disabled',
    ...(plan.offlineAtlassian ? { mcp: { atlassian: { enabled: false } } } : {}),
  }
  fs.writeFileSync(path.join(runDir, 'opencode.json'), JSON.stringify(config, null, 2), { mode: 0o600 })
  fs.writeFileSync(receipt, JSON.stringify({ run_id: runID, component: plan.component, export_status: 'not_started' }, null, 2), { mode: 0o600 })
  const env = {
    ...process.env, ...credentials,
    PWD: root,
    LANGFUSE_BASE_URL: host, LANGFUSE_HOST: host,
    LANGFUSE_USER_ID: hashUser(credentials.LANGFUSE_USER_ID && credentials.LANGFUSE_USER_ID !== 'anonymous' ? credentials.LANGFUSE_USER_ID : os.userInfo().username),
    LANGFUSE_ENVIRONMENT: credentials.LANGFUSE_ENVIRONMENT || 'development',
    OPENCODE_CONFIG: path.join(runDir, 'opencode.json'),
    OPENCODE_CONFIG_DIR: path.join(root, '.opencode'),
    OPENCODE_DEDICATED_TRACE: '1', AI_HELPERS_REPO: root,
    UXD_TRACE_COMPONENT: plan.component, UXD_TRACE_RUN_ID: runID,
    UXD_TRACE_WORKSPACE: plan.workspace, UXD_TRACE_TICKET: plan.ticket,
    UXD_TRACE_ARTIFACT_DIR: path.join(plan.workspace, '.artifacts', plan.ticket, 'runs', runID),
    UXD_TRACE_RUN_KIND: plan.runKind, UXD_TRACE_PROTOTYPE_URL: plan.prototypeURL,
    UXD_TRACE_INPUT_FINGERPRINT: plan.inputFingerprint,
    UXD_TRACE_OFFLINE_ATLASSIAN: String(plan.offlineAtlassian),
    UXD_TRACE_CONTEXT_FILE: plan.contextFile || '', UXD_TRACE_CONTEXT_SHA256: plan.contextSha256 || '',
    UXD_TRACE_RECEIPT: receipt, UXD_TRACE_PIPELINE_RESULT: pipelineResult,
    UXD_TRACE_SOURCE_REVISION: spawnSync('git', ['-C', root, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).stdout.trim(),
    UXD_TRACE_SOURCE_DIRTY: String(Boolean(spawnSync('git', ['-C', root, 'status', '--porcelain'], { encoding: 'utf8' }).stdout.trim())),
    UXD_TRACE_ESTIMATE_APPROVED: String(plan.approveEstimate),
    UXD_EVAL_ENV_FILE: credentialFile, LANGFUSE_ENABLED: '1',
  }
  // Never carry another session's parent context into this new root.
  delete env.LANGFUSE_TRACE_ID
  delete env.LANGFUSE_PARENT_SPAN_ID
  console.error(`Run: ${runID}\nReceipt: ${receipt}`)
  const child = spawn('opencode', plan.argv, { cwd: root, env, stdio: 'inherit' })
  const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('exit', (code, signal) => resolve(code ?? (signal ? 130 : 1))) })
  let final
  try { final = JSON.parse(fs.readFileSync(receipt, 'utf8')) } catch { final = {} }
  if (final.trace_id) console.error(`Hosted trace: ${traceURL(host, credentials.LANGFUSE_PROJECT_ID, final.trace_id)}`)
  console.error(`Export: ${final.export_status || 'unknown'}; task outcome: ${final.task_outcome || 'unconfirmed'}. Receipt: ${receipt}`)
  const verification = await verifyRemote(final, credentials)
  const verificationFile = path.join(runDir, 'remote-verification.json')
  fs.writeFileSync(verificationFile, JSON.stringify(verification, null, 2), { mode: 0o600 })
  console.error(`Remote ingestion: ${verification.status}. Verification: ${verificationFile}`)
  if (verification.status !== 'verified') console.error('Trace completeness is unverified. Recheck the receipt with scripts/verify-langfuse-receipt.mjs; do not rerun model work to repair telemetry.')
  process.exitCode = code || (final.export_status !== 'flush_completed' || final.task_outcome !== 'completed' || verification.status !== 'verified' ? 2 : 0)
}
main().catch(error => fail(error.message))
