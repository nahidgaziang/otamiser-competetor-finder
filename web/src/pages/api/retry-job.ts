import type { APIRoute } from 'astro';
import { queryAdmin } from '../../lib/db';

export const POST: APIRoute = async ({ request, redirect }) => {
  const formData = await request.formData();
  const jobId = formData.get('job_id')?.toString();

  if (!jobId) {
    return new Response('Missing job_id parameter', { status: 400 });
  }

  try {
    const res = await queryAdmin(
      `SELECT app.retry_job($1::uuid, 'admin_ui');`,
      [jobId]
    );

    if (res.rows[0]?.retry_job) {
      await queryAdmin(
        `INSERT INTO app.admin_audit_log (action, entity_type, entity_id, actor, details)
         VALUES ('retry_job', 'job', $1, 'admin_user', '{"status": "queued"}'::jsonb);`,
        [jobId]
      );
    }

    return redirect('/admin/jobs');
  } catch (err: any) {
    console.error('Retry job error:', err);
    return new Response('Internal failure processing request.', { status: 500 });
  }
};
