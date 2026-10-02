import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'

export const hashUser = value => /^sha256:[a-f0-9]{16}$/.test(value) ? value : `sha256:${crypto.createHash('sha256').update(value).digest('hex').slice(0, 16)}`
export const traceURL = (host, project, id) => `${host.replace(/\/$/, '')}/project/${encodeURIComponent(project)}/traces/${id}`
export const canonicalProjects = { creator: 'cmualk91e001f1i02s1usk3fn', consistency: 'cmualghc9001c1i02kfzzxxxf', evaluator: 'cmu4960wj00061i02oox0derw' }
export const canonicalHost = 'https://langfuse-ux-eval.apps.rosa.uxdpoc7.9hji.p3.openshiftapps.com'
export const nestedSession = env => Boolean(env.OPENCODE || env.OPENCODE_DEDICATED_TRACE || env.OPENCODE_SESSION_ID || env.CLAUDECODE || env.CODEX_THREAD_ID)
export function validateRuntime(version) {
  const [major, minor, patch] = version.split('.').map(Number)
  if (!(major >= 26 || major === 24 && (minor > 15 || minor === 15 && patch >= 0) || major === 22 && (minor > 22 || minor === 22 && patch >= 2))) throw new Error('Node version is below the locked dependency requirement. Use Node 24.15.0+ within 24.x.')
}
export function readAssignments(file) {
  const stat = fs.lstatSync(file)
  if (!stat.isFile() || stat.isSymbolicLink() || (stat.mode & 0o777) !== 0o600) throw new Error('Credential file must be a regular, non-symlink file with mode 600.')
  const result = {}
  const allowed = new Set(['LANGFUSE_BASE_URL', 'LANGFUSE_HOST', 'LANGFUSE_PROJECT_ID', 'LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY', 'LANGFUSE_USER_ID', 'LANGFUSE_ENVIRONMENT', 'OPENAI_API_KEY'])
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    if (!line.trim() || line.trim().startsWith('#')) continue
    const match = line.match(/^(?:export )?([A-Z_]+)=(.*)$/)
    if (!match || !allowed.has(match[1])) throw new Error('Credential file accepts only documented KEY=value assignments, not shell commands.')
    let value = match[2].trim()
    if (/^["']/.test(value)) {
      if (value.at(-1) !== value[0]) throw new Error('Unclosed quote in credential assignment.')
      value = value.slice(1, -1)
    }
    if (/[\r\n`$]/.test(value)) throw new Error('Credential assignments must be literal values, without shell expansion.')
    result[match[1]] = value
  }
  return result
}
const required = (file, message) => { if (!fs.existsSync(file)) throw new Error(message) }
export function buildPlan(args, root) {
  const component = args[0]
  const commands = { creator: 'designer-create', consistency: 'designer-consistency', evaluator: 'designer-evaluate' }
  if (!commands[component]) throw new Error('Usage: trace-in-langfuse <creator|consistency|evaluator> --ticket KEY|none --workspace ABSOLUTE_PATH --prototype-url URL|none --scenario TEXT [--model PROVIDER/MODEL] [--dry-run|--verify] [--approve-estimate]')
  const opts = {}
  const flags = new Set(['--dry-run', '--verify', '--approve-estimate', '--offline-atlassian'])
  const values = new Set(['--ticket', '--workspace', '--prototype-url', '--scenario', '--model', '--run-kind', '--context-file'])
  for (let i = 1; i < args.length; i++) {
    const name = args[i]
    if (name in opts) throw new Error(`Duplicate option: ${name}`)
    if (flags.has(name)) opts[name] = true
    else if (values.has(name) && args[i + 1] && !args[i + 1].startsWith('--')) opts[name] = args[++i]
    else throw new Error(`Unknown or incomplete option: ${name}`)
  }
  const verify = Boolean(opts['--verify']), dryRun = Boolean(opts['--dry-run']), approveEstimate = Boolean(opts['--approve-estimate'])
  if (verify && dryRun || approveEstimate && (component !== 'evaluator' || verify)) throw new Error('Invalid verify/dry-run/paid-approval combination.')
  if (verify) return { component, verify }
  for (const name of ['--ticket', '--workspace', '--prototype-url', '--scenario']) if (!opts[name]) throw new Error(`Missing ${name}`)
  const ticket = opts['--ticket']
  if (!/^(?:none|[A-Z][A-Z0-9_]*-\d+)$/.test(ticket)) throw new Error('--ticket must be a Jira key or none.')
  const workspaceArg = opts['--workspace']
  if (!path.isAbsolute(workspaceArg) || !fs.existsSync(workspaceArg) || !fs.statSync(workspaceArg).isDirectory()) throw new Error('--workspace must be an existing absolute directory.')
  const workspace = fs.realpathSync(workspaceArg)
  if (/[\r\n*?\[\]{}]/.test(workspace)) throw new Error('Workspace paths cannot contain newlines or permission-pattern metacharacters.')
  const offlineAtlassian = Boolean(opts['--offline-atlassian'])
  let contextFile, contextSha256
  if (opts['--context-file']) {
    const file = opts['--context-file']
    if (!path.isAbsolute(file) || !fs.existsSync(file) || !fs.statSync(file).isFile()) throw new Error('--context-file must be an existing absolute file path.')
    contextFile = fs.realpathSync(file)
    const inside = parent => { const relative = path.relative(fs.realpathSync(parent), contextFile); return relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative) }
    if (!inside(root) && !inside(workspace)) throw new Error('Stage the context file inside the fork or selected workspace to avoid external-directory prompts.')
    contextSha256 = crypto.createHash('sha256').update(fs.readFileSync(contextFile)).digest('hex')
  }
  if (offlineAtlassian && (!contextFile || component === 'evaluator')) throw new Error('--offline-atlassian requires --context-file and a creator or consistency run.')
  const scenario = opts['--scenario'], prototypeURL = opts['--prototype-url']
  if (/[\r\n]/.test(scenario)) throw new Error('--scenario must be one line.')
  if (prototypeURL !== 'none' && !/^https?:\/\/[^\s]+$/.test(prototypeURL)) throw new Error('--prototype-url must be an HTTP(S) URL or none.')
  if (component === 'evaluator' && prototypeURL === 'none') throw new Error('Evaluator requires a served prototype URL, including smoke runs.')
  const runKind = opts['--run-kind'] || 'manual-designer-test'
  if (!['manual-smoke', 'manual-designer-test', 'manual-regression'].includes(runKind)) throw new Error('Invalid --run-kind.')
  if (ticket === 'none' && component === 'evaluator' && runKind !== 'manual-smoke') throw new Error('Evaluator ticket=none is supported only for manual-smoke with explicit synthetic requirements.')
  const model = opts['--model']
  if (model && !/^[\w.-]+\/[\w.+-]+$/.test(model)) throw new Error('--model must be PROVIDER/MODEL.')
  const command = commands[component]
  const commandFile = path.join(root, '.opencode/command', `${command}.md`)
  required(commandFile, `Missing ${commandFile}. Use jaquevan/ai-helpers beau-testing with designer commands (bdbb588 or later) and the fork-owned tracing runtime.`)
  const skill = component === 'creator' ? 'plugins/uxd-prototype/skills/uxd-prototype-create' : component === 'consistency' ? 'plugins/uxd-prototype/skills/uxd-consistency-check' : 'plugins/uxd-prototype/skills/uxd-prototype-evaluate'
  required(path.join(root, skill), `Missing ${skill}; update beau-testing.`)
  const inputFingerprint = crypto.createHash('sha256').update(JSON.stringify({ component, ticket, workspace, prototypeURL, runKind, scenario, model: model || 'default', ...(contextFile ? { contextFile, contextSha256, offlineAtlassian } : {}) })).digest('hex')
  const header = `[UXD-SESSION]\ncomponent=${component}\nrun_kind=${runKind}\nticket=${ticket}\nworkspace=${workspace}\nprototype_url=${prototypeURL}\nscenario=${scenario}`
  let prompt = `${header}\n\nTask: ${scenario}\n\nThis is a noninteractive session. If required input or permission is missing, stop and report outcome=blocked with a focused question in your final text; do not use the question tool. Read UXD_TRACE_RUN_ID and UXD_TRACE_RECEIPT individually, never dump the environment. Follow docs/opencode-designer-session-protocol.md.`
  prompt += '\nKeep newly written server logs, screenshots and scratch outputs inside the selected workspace. UXD_TRACE_ARTIFACT_DIR names this run’s workspace-local artifact directory; create it if needed and use its server.log for server output. Do not write logs to /tmp and then request access to read them. When starting a local server, poll its URL with a bounded readiness wait before concluding startup failed; verify that its process belongs to the selected workspace.'
  if (contextFile) prompt += `\nRead the local source snapshot at ${JSON.stringify(contextFile)} (SHA-256 ${contextSha256}). Distinguish source requirements from proposed refinement checks.`
  if (offlineAtlassian) prompt += '\nJIRA IS READ-ONLY. The snapshot was prepared through read-only access. Atlassian MCP is disabled for this child session: use the snapshot instead of fetching Jira. Never create, edit, comment, transition, attach, link, watch or otherwise write to Jira/Confluence, including through shell commands, scripts or HTTP APIs. Do not post findings remotely.'
  if (component === 'evaluator') {
    const pipeline = path.join(root, skill, 'scripts/langfuse-trace-pipeline.py')
    required(pipeline, 'Missing Langfuse evaluator pipeline; use the GitHub fork beau-testing.')
    const source = fs.readFileSync(pipeline, 'utf8')
    for (const flag of ['--personal-run', '--estimate-only', '--approve-estimate']) if (!source.includes(flag)) throw new Error(`Stale evaluator pipeline: missing ${flag}`)
    const benchmark = path.join(root, 'tmp/personal-runs', ticket, inputFingerprint)
    prompt += `\nRun the pipeline exactly once using node ${JSON.stringify(path.join(root, 'scripts/trace-eval-run.mjs'))} ${JSON.stringify(path.join(root, '.venv/bin/python'))} ${JSON.stringify(pipeline)}. Pass --provider openai, --key ${ticket}, --workspace ${JSON.stringify(workspace)}, --url ${JSON.stringify(prototypeURL)}, --benchmark-dir ${JSON.stringify(benchmark)}, --jira-context ${JSON.stringify(path.join(benchmark, 'jira-context.json'))}, --personal-run and --trace-sanitized-artifacts. Use a 3600000 ms tool timeout. No standalone phases, Qwen judging or paid retries.`
    prompt += approveEstimate ? '\nThe user separately approved the prior estimate. Reuse the staged context unchanged; the pipeline must verify its saved estimate. Pass --approve-estimate once. Stop on the first failure.' : '\nStage fresh source context, then pass --estimate-only once. Show the full estimate and stop. Do not execute paid evaluator phases.'
    if (ticket === 'none' && !approveEstimate) prompt += '\nFor this smoke run only, stage {"source":"synthetic-smoke","ticket":{"key":"none","summary":"Synthetic smoke requirements","description":"<supplied scenario>","acceptance_criteria":["<explicit scenario criterion>"]}}. Include only requirements explicitly stated in the scenario. Do not query Jira or invent acceptance criteria.'
  }
  const template = fs.readFileSync(commandFile, 'utf8').replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n/, '')
  // OpenCode resolves its session directory from inherited PWD unless --dir is
  // explicit. spawn({ cwd: root }) alone does not replace that environment value.
  const argv = ['run', '--dir', root, ...(model ? ['--model', model] : []), '--command', command, prompt]
  return { component, verify, dryRun, approveEstimate, ticket, workspace, prototypeURL, runKind, model, inputFingerprint, contextFile, contextSha256, offlineAtlassian, command, argv, renderedTemplate: template.replaceAll('$ARGUMENTS', prompt), workspacePolicy: 'per-run scoped allow; explicit existing deny rules remain authoritative' }
}
