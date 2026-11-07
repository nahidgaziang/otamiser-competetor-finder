import type { APIRoute } from 'astro';
import { queryAdmin } from '../../lib/db';

export const POST: APIRoute = async ({ request, redirect }) => {
  const formData = await request.formData();
  const competitorId = formData.get('competitor_id')?.toString();
  const action = formData.get('action')?.toString();

  if (!competitorId || !action) {
    return new Response('Missing required parameters', { status: 400 });
  }

  try {
    if (action === 'approve') {
      // 1. Enqueue research job through SECURITY DEFINER stored function
      await queryAdmin(
        `SELECT app.request_job('research', jsonb_build_object('competitor_id', $1::text), 'admin_ui');`,
        [competitorId]
      );

      // 2. Update competitor status to covered/in_progress
      await queryAdmin(
        `UPDATE app.competitors SET status = 'covered', updated_at = now() WHERE id = $1;`,
        [competitorId]
      );

      // 3. Log admin action
      await queryAdmin(
        `INSERT INTO app.admin_audit_log (action, entity_type, entity_id, actor, details)
         VALUES ('approve_competitor', 'competitor', $1, 'admin_user', '{"queued_job": "research"}'::jsonb);`,
        [competitorId]
      );
    } else if (action === 'skip') {
      await queryAdmin(
        `UPDATE app.competitors SET status = 'ignored', updated_at = now() WHERE id = $1;`,
        [competitorId]
      );

      await queryAdmin(
        `INSERT INTO app.admin_audit_log (action, entity_type, entity_id, actor, details)
         VALUES ('skip_competitor', 'competitor', $1, 'admin_user', '{"status": "ignored"}'::jsonb);`,
        [competitorId]
      );
    }

    return redirect('/admin/candidates');
  } catch (err: any) {
    console.error('Candidate action error:', err);
    return new Response(`Action failed: ${err.message}`, { status: 500 });
  }
};
