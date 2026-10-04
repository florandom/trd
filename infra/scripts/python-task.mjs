import { existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const localUv = resolve(root, '.tools', 'uv', 'bin', process.platform === 'win32' ? 'uv.exe' : 'uv');
const uv = existsSync(localUv) ? localUv : 'uv';
const child = spawn(uv, ['run', '--frozen', 'python', 'infra/scripts/task.py', ...process.argv.slice(2)], {
  cwd: root, stdio: 'inherit', shell: false,
});
child.on('error', () => {
  console.error('Install uv 0.12.22, then retry. See README.md (Local boot).');
  process.exitCode = 1;
});
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => child.kill(signal));
}
child.on('exit', (code) => { process.exitCode = code ?? 1; });
