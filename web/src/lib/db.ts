import pg from 'pg';

if (!process.env.DATABASE_URL_WEB && typeof process.loadEnvFile === 'function') {
  for (const envPath of ['.env', '../.env', '../../.env']) {
    try {
      process.loadEnvFile(envPath);
      if (process.env.DATABASE_URL_WEB) break;
    } catch {
      // ignore
    }
  }
}

const { Pool } = pg;

const WEB_DB_URL = process.env.DATABASE_URL_WEB || 'postgresql://web_app@127.0.0.1:5432/otamiser_local';

// Admin Pool (web_app role)
export const poolAdmin = new Pool({
  connectionString: WEB_DB_URL,
  max: 10,
  idleTimeoutMillis: 30000,
});

// Hub Pool (read-only queries)
export const poolHub = new Pool({
  connectionString: WEB_DB_URL,
  max: 10,
  idleTimeoutMillis: 30000,
});

export async function queryHub(text: string, params: any[] = []) {
  const client = await poolHub.connect();
  try {
    return await client.query(text, params);
  } finally {
    client.release();
  }
}

export async function queryAdmin(text: string, params: any[] = []) {
  const client = await poolAdmin.connect();
  try {
    return await client.query(text, params);
  } finally {
    client.release();
  }
}

