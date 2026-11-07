import type { APIRoute } from 'astro';
import { queryAdmin } from '../../lib/db';

export const POST: APIRoute = async ({ request, redirect }) => {
  const formData = await request.formData();
  const kind = formData.get('kind')?.toString();

  if (!kind) {
    return new Response('Missing kind parameter', { status: 400 });
  }

  try {
    await queryAdmin(
      `SELECT app.request_job($1, '{}'::jsonb, 'admin_ui');`,
      [kind]
    );

    await queryAdmin(
      `INSERT INTO app.admin_audit_log (action, entity_type, actor, details)
       VALUES ('trigger_job', 'job', 'admin_user', jsonb_build_object('kind', $1::text));`,
      [kind]
    );

    return redirect('/admin/jobs');
  } catch (err: any) {
    console.error('Trigger job error:', err);
    return new Response('Internal failure processing request.', { status: 500 });
  }
};

