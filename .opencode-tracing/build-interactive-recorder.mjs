import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { validateRuntime } from './runtime.mjs'

// Build an auditable adapter from the exact installed MIT-licensed upstream
// bundle. No eval, runtime source patching, credential reads or network access.
export const upstreamSHA256 = '85441be4fab7fb85a92fd998d55d3d61c99152e588b3b7257bcf2d363f36fe7e'
export function adaptRecorder(source) {
  if (crypto.createHash('sha256').update(source).digest('hex') !== upstreamSHA256) throw new Error('Upstream 0.4.0 recorder hash differs; review adapter against this build before proceeding')
  const replace = (before, after) => {
    if (source.split(before).length !== 2) throw new Error('Upstream recorder adapter seam differs')
    source = source.replace(before, after)
  }
  replace('tracer: trace.getTracer(tracerName, PLUGIN_VERSION),', 'tracer: input.tracer,')
  replace('\t\tthis.baseUrl = input.baseUrl;', '\t\tthis.baseUrl = input.baseUrl;\n\t\tthis.context = input.context;')
  if ((source.match(/context\.with/g) || []).length !== 5 || (source.match(/context\.active/g) || []).length !== 5) throw new Error('Upstream context adapter seam differs')
  source = source.replaceAll('context.with(', 'this.context.with(').replaceAll('context.active()', 'this.context.active()')
  const start = source.indexOf('\tconst processor = new LangfuseSpanProcessor({', source.indexOf('const createLangfuseClient'))
  const end = source.indexOf('\n});\n//#endregion', start)
  if (start < 0 || end < start) throw new Error('Upstream provider adapter seam differs')
  source = source.slice(0, start) + `\treturn new LangfuseClient({
\t\tbaseUrl: input.baseUrl,
\t\tcontext: input.context,
\t\ttraceState,
\t\tforceFlush: Effect.tryPromise(() => input.forceFlush()),
\t\tshutdown: Effect.tryPromise(() => input.shutdown())
\t});` + source.slice(end)
  replace('const main = Effect.gen(function* () {', 'const main = (runtime) => Effect.gen(function* () {')
  const credentialsStart = source.indexOf('\tconst langfuse = yield* Effect.gen(function* () {', source.indexOf('const main ='))
  const credentialsEnd = source.indexOf('\n\tif (!langfuse) return {};', credentialsStart)
  if (credentialsStart < 0 || credentialsEnd < credentialsStart) throw new Error('Upstream credential adapter seam differs')
  source = source.slice(0, credentialsStart) + '\tconst langfuse = yield* createLangfuseClient(runtime);' + source.slice(credentialsEnd)
  replace('const LangfusePlugin = async ({ client }) => {', 'const LangfusePlugin = async ({ client }, runtime) => {')
  replace('main.pipe(Effect.provide(clientLayer))', 'main(runtime).pipe(Effect.provide(clientLayer))')
  // Keep turn cleanup, but preserve lifetime message/generation dedup at idle.
  // The router additionally journals completed message IDs across restarts.
  replace('\t\t\tthis.traceState.tracedMessageIds.delete(messageID);', '\t\t\t// Retain user-message dedup across interactive idle.')
  replace('\t\t\tthis.traceState.tracedGenerationIds.delete(messageID);', '\t\t\t// Retain generation dedup across interactive idle.')
  return '// Generated from MIT-licensed @langfuse/opencode-observability-plugin 0.4.0. See recorder-adapter.md.\n' + source.replace(/\n\/\/# sourceMappingURL=index.js.map\s*$/, '\n')
}
export function buildRecorder(root = path.dirname(fileURLToPath(import.meta.url))) {
  validateRuntime(process.versions.node)
  const upstream = path.join(root, 'node_modules/@langfuse/opencode-observability-plugin')
  if (JSON.parse(fs.readFileSync(path.join(upstream, 'package.json'), 'utf8')).version !== '0.4.0') throw new Error('Install the locked upstream recorder 0.4.0')
  const source = adaptRecorder(fs.readFileSync(path.join(upstream, 'dist/index.js'), 'utf8'))
  const destination = path.join(root, 'generated')
  fs.mkdirSync(destination, { recursive: true })
  fs.writeFileSync(path.join(destination, 'interactive-recorder.mjs'), source)
  fs.copyFileSync(path.join(upstream, 'LICENSE'), path.join(destination, 'UPSTREAM-LICENSE'))
  return path.join(destination, 'interactive-recorder.mjs')
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { console.log(`Built interactive recorder: ${buildRecorder()}`) }
  catch { console.error('Interactive recorder build failed. Check locked dependencies, Node version and upstream hash. No configuration changed.'); process.exitCode = 1 }
}
