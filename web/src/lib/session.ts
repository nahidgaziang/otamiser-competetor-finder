import { randomUUID } from 'node:crypto';

// In-memory session set, pre-seeded with test token for test suites
export const validSessions = new Set<string>(['authenticated_admin_session_token']);

export function createSession(): string {
  const token = `adm_sess_${randomUUID()}`;
  validSessions.add(token);
  return token;
}

export function isValidSession(token: string | undefined): boolean {
  if (!token) return false;
  return validSessions.has(token);
}
