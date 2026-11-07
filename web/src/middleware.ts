import { defineMiddleware } from 'astro:middleware';
import { isValidSession } from './lib/session';

export const onRequest = defineMiddleware(async (context, next) => {
  const url = new URL(context.request.url);

  // Auth check for /admin routes (except /admin/login) BEFORE next()
  if (url.pathname.startsWith('/admin') && !url.pathname.startsWith('/admin/login')) {
    const sessionCookie = context.cookies.get('admin_session')?.value;
    if (!isValidSession(sessionCookie)) {
      return context.redirect('/admin/login');
    }
  }

  // Auth check for /api routes
  if (url.pathname.startsWith('/api')) {
    const sessionCookie = context.cookies.get('admin_session')?.value;
    if (!isValidSession(sessionCookie)) {
      return new Response(JSON.stringify({ error: 'Unauthorized: admin session required' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    }
  }

  // Execute request
  const response = await next();

  // Security headers for all responses
  response.headers.set('X-Robots-Tag', 'noindex, nofollow');
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  response.headers.set(
    'Content-Security-Policy',
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-src 'self'; frame-ancestors 'none';"
  );

  return response;
});
