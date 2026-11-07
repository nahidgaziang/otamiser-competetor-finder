import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';

let server: ChildProcess | undefined;

export const E2E_PORT = process.env.E2E_PORT ?? '4398';

function requireTestDatabase(): void {
  for (const key of ['DATABASE_URL', 'DATABASE_URL_WEB']) {
    const value = process.env[key];
    if (!value) throw new Error(`E2E tests need ${key} (pointing at a disposable *_test database)`);
    const db = new URL(value).pathname.replace(/^\//, '');
    if (!db.endsWith('_test')) {
      throw new Error(`Refusing to run E2E tests against '${db}': database name must end in _test`);
    }
  }
}

export async function setup(): Promise<void> {
  requireTestDatabase();
  if (!existsSync('dist/server/entry.mjs')) {
    throw new Error('Build the app first: npm run build');
  }
  server = spawn(process.execPath, ['dist/server/entry.mjs'], {
    env: { ...process.env, PORT: E2E_PORT, HOST: '127.0.0.1' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let log = '';
  server.stdout?.on('data', (d) => (log += d));
  server.stderr?.on('data', (d) => (log += d));

  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${E2E_PORT}/compare`);
      if (res.status < 500) return;
    } catch {
      // not listening yet
    }
    await new Promise((r) => setTimeout(r, 300));
  }
  server.kill();
  throw new Error(`Server did not start on port ${E2E_PORT}:\n${log}`);
}

export async function teardown(): Promise<void> {
  server?.kill();
}
