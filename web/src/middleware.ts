import { defineMiddleware } from 'astro:middleware';

export const onRequest = defineMiddleware(async (context, next) => {
  const url = new URL(context.request.url);

  // Security headers for all responses
  const response = await next();
  response.headers.set('X-Robots-Tag', 'noindex, nofollow');
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  response.headers.set(
    'Content-Security-Policy',
    "default-src 'self' 'unsafe-inline'; frame-src 'self'; frame-ancestors 'none';"
  );

  // Auth check for /admin routes (except /admin/login)
  if (url.pathname.startsWith('/admin') && !url.pathname.startsWith('/admin/login')) {
    const sessionCookie = context.cookies.get('admin_session')?.value;
    if (!sessionCookie) {
      // In local dev without active session, redirect to login
      return context.redirect('/admin/login');
    }
  }

  return response;
});

