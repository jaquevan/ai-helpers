import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
// A PTY exercises the production consent gate. Every external service/model
// executable is mocked; this never exports a trace or invokes a model.
test('terminal launch accepts stderr help and pins --dir and PWD despite a different caller directory', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'trace-terminal-'))
  let runDir
  try {
    const home = path.join(temp, 'home'), bin = path.join(temp, 'bin'), captured = path.join(temp, 'argv.json')
    fs.mkdirSync(path.join(home, '.config/opencode/langfuse'), { recursive: true }); fs.mkdirSync(bin)
    for (const component of ['creator', 'consistency', 'evaluator']) fs.writeFileSync(path.join(home, `.config/opencode/langfuse/${component}.env`), `LANGFUSE_BASE_URL=https://synthetic.test\nLANGFUSE_PROJECT_ID=${component}-project\nLANGFUSE_PUBLIC_KEY=${component}-public\nLANGFUSE_SECRET_KEY=synthetic-${component}-credential\n`, { mode: 0o600 })
    const mock = (name, body) => fs.writeFileSync(path.join(bin, name), `#!${process.execPath}\n${body}`, { mode: 0o755 })
    mock('ps', '')
    mock('curl', `let s='';process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>{const expected=Buffer.from('creator-public:synthetic-creator-credential').toString('base64');if(!s.includes(expected))process.exit(22);console.log(JSON.stringify({data:process.argv.some(a=>a.includes('/v2/observations'))?[{id:'root',traceId:'a'.repeat(32),type:'SPAN',isRootObservation:true}]:[{id:'creator-project'}]}))})`)
    mock('opencode', `const fs=require('fs'); const a=process.argv.slice(2);if(a[0]==='--version')console.log('1.18.31');else if(a.includes('--help'))console.error('--command');else {fs.writeFileSync(process.env.CAPTURE,JSON.stringify({argv:a,cwd:process.cwd(),pwd:process.env.PWD,receipt:process.env.UXD_TRACE_RECEIPT,user:process.env.LANGFUSE_USER_ID}));fs.writeFileSync(process.env.UXD_TRACE_RECEIPT,JSON.stringify({trace_id:'a'.repeat(32),generations:0,tool_calls:0,user_turns:0,known_session_cost_usd:0,export_status:'flush_completed',task_outcome:'completed'}))}`)
    const env = { ...process.env, HOME: home, PWD: temp, PATH: `${bin}:${process.env.PATH}`, CAPTURE: captured }
    for (const name of ['OPENCODE', 'OPENCODE_SESSION_ID', 'OPENCODE_DEDICATED_TRACE', 'CLAUDECODE', 'CODEX_THREAD_ID']) delete env[name]
    const launcher = path.join(root, '.opencode-tracing/launcher.mjs')
    const wrongProject = spawnSync(process.execPath, [launcher, 'consistency', '--verify'], { env, encoding: 'utf8' })
    assert.equal(wrongProject.status, 2)
    assert.match(wrongProject.stderr, /No fallback/)
    const python = `import os,pty,select,sys,time,json\npid,fd=pty.fork()\nif pid==0: os.execve(sys.argv[1],sys.argv[1:],os.environ)\ndata=b'';sent=False;end=time.time()+20\nwhile time.time()<end:\n if select.select([fd],[],[],0.2)[0]:\n  try: chunk=os.read(fd,65536)\n  except OSError: break\n  if not chunk: break\n  data+=chunk\n  if b'Type TRACE here' in data and not sent: os.write(fd,b'TRACE\\n');sent=True\nelse:\n os.kill(pid,9)\n raise RuntimeError('PTY timeout')\n_,status=os.waitpid(pid,0)\nprint(data.decode(errors='replace'))\nsys.exit(os.waitstatus_to_exitcode(status))`
    const result = spawnSync('python3', ['-c', python, process.execPath, launcher, 'creator', '--ticket', 'none', '--workspace', temp, '--prototype-url', 'none', '--scenario', 'Synthetic routing fixture', '--model', 'test/model'], { env, encoding: 'utf8', timeout: 30000 })
    assert.equal(result.status, 0, result.stderr + result.stdout)
    const actual = JSON.parse(fs.readFileSync(captured, 'utf8'))
    runDir = path.dirname(actual.receipt)
    assert.deepEqual(actual.argv.slice(0, 7), ['run', '--dir', root, '--model', 'test/model', '--command', 'designer-create'])
    assert.equal(actual.cwd, fs.realpathSync(root))
    assert.equal(actual.pwd, root)
    assert.match(actual.argv.at(-1), /^\[UXD-SESSION\]/)
    assert.match(actual.user, /^sha256:[a-f0-9]{16}$/)
    assert.match(result.stdout, /Remote ingestion: verified/)
  } finally {
    if (runDir) fs.rmSync(runDir, { recursive: true, force: true })
    fs.rmSync(temp, { recursive: true, force: true })
  }
})
