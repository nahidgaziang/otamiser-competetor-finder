/**
 * Security and publishing-safety tests for the hub and admin (build guide sections 0, 8, 10; goals V9, V12).
 *
 * `it.fails(...)` marks a test that asserts the correct behaviour but currently fails because of a
 * confirmed defect (BUG-WEBx in reports/code-review.md). If a defect is fixed, the test starts
 * passing, Vitest reports it as a failure, and the `.fails` must be removed.
 *
 * Requests without an Origin header model non-browser clients (curl, scripts, other local apps).
 */
import { afterAll, beforeEach, describe, expect, it } from 'vitest';
import pg from 'pg';
import { randomUUID } from 'node:crypto';

const PORT = process.env.E2E_PORT ?? '4398';
const BASE = `http://127.0.0.1:${PORT}`;
const db = new pg.Pool({ connectionString: process.env.DATABASE_URL, max: 2 });

type Seeded = { competitorId: string; articleId: string; slug: string; marker: string };

async function seedArticle(opts: { status: string; gatePassed: boolean }): Promise<Seeded> {
  const tag = randomUUID().slice(0, 8);
  const marker = `E2E-MARKER-${tag}`;
  const comp = await db.query(
    `INSERT INTO app.competitors (name, canonical_domain, status) VALUES ($1, $2, 'candidate') RETURNING id`,
    [`E2E ${marker}`, `e2e-${tag}.example`],
  );
  const slug = `otamiser-vs-e2e-${tag}`;
  const art = await db.query(
    `INSERT INTO app.articles (competitor_id, slug, status) VALUES ($1, $2, $3) RETURNING id`,
    [comp.rows[0].id, slug, opts.status],
  );
  const content = { title: `Draft ${marker}`, meta_description: 'x'.repeat(130) };
  const ver = await db.query(
    `INSERT INTO app.article_versions (article_id, version_number, content, webflow_html, gate_report)
     VALUES ($1, 1, $2, $3, $4) RETURNING id`,
    [art.rows[0].id, JSON.stringify(content), `<p>${marker}</p>`, JSON.stringify({ all_passed: opts.gatePassed, checks: {} })],
  );
  await db.query(`UPDATE app.articles SET current_version_id = $1 WHERE id = $2`, [ver.rows[0].id, art.rows[0].id]);
  return { competitorId: comp.rows[0].id, articleId: art.rows[0].id, slug, marker };
}

async function articleStatus(id: string): Promise<string> {
  return (await db.query(`SELECT status FROM app.articles WHERE id = $1`, [id])).rows[0].status;
}

function form(data: Record<string, string>): URLSearchParams {
  return new URLSearchParams(data);
}

async function post(path: string, data: Record<string, string>, headers: Record<string, string> = {}) {
  return fetch(`${BASE}${path}`, { method: 'POST', body: form(data), redirect: 'manual', headers });
}

/** A session cookie as the login page issues it (also obtainable without credentials, see BUG-WEB3). */
const SESSION = { cookie: 'admin_session=authenticated_admin_session_token' };

beforeEach(async () => {
  await db.query(`DELETE FROM app.jobs`);
});

afterAll(async () => {
  await db.query(`DELETE FROM app.competitors WHERE name LIKE 'E2E %'`);
  await db.query(`DELETE FROM app.admin_audit_log WHERE created_at > now() - interval '1 hour'`);
  await db.end();
});

describe('public comparison hub', () => {
  it('serves a published article', async () => {
    const a = await seedArticle({ status: 'published', gatePassed: true });
    const res = await fetch(`${BASE}/compare/${a.slug}`, { redirect: 'manual' });
    expect(res.status).toBe(200);
  });

  it('BUG-WEB1: never serves unpublished drafts (/compare/[slug] has no status filter)', async () => {
    const a = await seedArticle({ status: 'needs_attention', gatePassed: false });
    const res = await fetch(`${BASE}/compare/${a.slug}`, { redirect: 'manual' });
    const body = res.status === 200 ? await res.text() : '';
    expect(body).not.toContain(a.marker);
  });

  it('sends noindex, nosniff and anti-framing headers', async () => {
    const res = await fetch(`${BASE}/compare`);
    expect(res.headers.get('x-robots-tag')).toContain('noindex');
    expect(res.headers.get('x-content-type-options')).toBe('nosniff');
    expect(res.headers.get('content-security-policy')).toContain("frame-ancestors 'none'");
  });

  it("BUG-WEB2: CSP does not allow inline scripts ('unsafe-inline' in default-src)", async () => {
    const csp = (await fetch(`${BASE}/compare`)).headers.get('content-security-policy') ?? '';
    const scriptSrc = /script-src([^;]*)/.exec(csp)?.[1] ?? /default-src([^;]*)/.exec(csp)?.[1] ?? '';
    expect(scriptSrc).not.toContain("'unsafe-inline'");
  });
});

describe('admin authentication', () => {
  it('redirects /admin to login without a session', async () => {
    const res = await fetch(`${BASE}/admin`, { redirect: 'manual' });
    expect(res.status).toBe(302);
    expect(res.headers.get('location')).toContain('/admin/login');
  });

  it('BUG-WEB3: rejects a forged session cookie (middleware only checks the cookie exists)', async () => {
    const res = await fetch(`${BASE}/admin`, { redirect: 'manual', headers: { cookie: 'admin_session=anything' } });
    expect(res.status).toBe(302);
  });

  it('BUG-WEB4: login page does not print the admin password', async () => {
    const body = await (await fetch(`${BASE}/admin/login`)).text();
    expect(body).not.toContain('admin123');
  });

  it('BUG-WEB5: hard-coded default credentials are not accepted', async () => {
    const res = await post('/admin/login', { email: 'admin@otamiser.local', password: 'admin123' });
    expect(res.headers.get('location')).not.toBe('/admin');
  });

  it('BUG-WEB6: each login gets a fresh random session token', async () => {
    const one = await post('/admin/login', { email: 'admin@otamiser.local', password: 'admin123' });
    const two = await post('/admin/login', { email: 'admin@otamiser.local', password: 'admin123' });
    const token = (r: Response) => /admin_session=([^;]+)/.exec(r.headers.get('set-cookie') ?? '')?.[1];
    expect(token(one)).toBeTruthy();
    expect(token(one)).not.toBe(token(two));
  });
});

describe('admin actions without a session', () => {
  it('rejects cross-site form posts (Astro checkOrigin)', async () => {
    const res = await post('/api/trigger-job', { kind: 'discover' }, { origin: 'https://evil.example' });
    expect(res.status).toBe(403);
  });

  it('BUG-WEB7: publishing requires a session (page action runs before the auth redirect)', async () => {
    const a = await seedArticle({ status: 'needs_review', gatePassed: true });
    await post(`/admin/articles/${a.articleId}`, { action: 'publish', confirm_text: 'PUBLISH' });
    expect(await articleStatus(a.articleId)).not.toBe('published');
  });

  it('BUG-WEB8: /api/trigger-job requires a session', async () => {
    await post('/api/trigger-job', { kind: 'discover' });
    const { rows } = await db.query(`SELECT count(*)::int AS n FROM app.jobs`);
    expect(rows[0].n).toBe(0);
  });

  it('BUG-WEB8: /api/candidate-action requires a session', async () => {
    const a = await seedArticle({ status: 'draft', gatePassed: false });
    await post('/api/candidate-action', { competitor_id: a.competitorId, action: 'skip' });
    const { rows } = await db.query(`SELECT status FROM app.competitors WHERE id = $1`, [a.competitorId]);
    expect(rows[0].status).toBe('candidate');
  });
});

describe('admin actions with a session', () => {
  it('records an audit entry when publishing', async () => {
    const a = await seedArticle({ status: 'needs_review', gatePassed: true });
    await post(`/admin/articles/${a.articleId}`, { action: 'publish', confirm_text: 'PUBLISH' }, SESSION);
    const { rows } = await db.query(
      `SELECT count(*)::int AS n FROM app.admin_audit_log WHERE action = 'publish_article' AND entity_id = $1`,
      [a.articleId],
    );
    expect(rows[0].n).toBe(1);
  });

  it('refuses to publish without the typed confirmation', async () => {
    const a = await seedArticle({ status: 'needs_review', gatePassed: true });
    await post(`/admin/articles/${a.articleId}`, { action: 'publish', confirm_text: 'yes' }, SESSION);
    expect(await articleStatus(a.articleId)).toBe('needs_review');
  });

  it('BUG-WEB9: refuses to publish an article whose gate failed', async () => {
    const a = await seedArticle({ status: 'needs_attention', gatePassed: false });
    await post(`/admin/articles/${a.articleId}`, { action: 'publish', confirm_text: 'PUBLISH' }, SESSION);
    expect(await articleStatus(a.articleId)).not.toBe('published');
  });

  it('BUG-WEB10: does not show raw database errors to the browser', async () => {
    const res = await post('/api/trigger-job', { kind: 'research' }, SESSION);
    expect(await res.text()).not.toMatch(/requires competitor_id|ERROR|relation|syntax/i);
  });

  it('BUG-WEB11: accepts same-origin form posts from the configured host 127.0.0.1', async () => {
    const res = await post('/api/trigger-job', { kind: 'discover' }, { ...SESSION, origin: BASE });
    expect(res.status).toBe(302);
  });
});
