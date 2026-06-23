import { PageHeader, Panel, StatusPill } from "@/components/ui";

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Settings"
        title="A small admin surface with a bigger deployment story."
        description="Local auth is intentionally absent in this MVP. The next layers from the plan are AWS role onboarding, a reusable collector command, Helm packaging, and public deployment controls."
      />

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Current defaults" subtitle="MVP assumptions reflected in this scaffold">
          <div className="space-y-3 rounded-[24px] bg-white/75 p-5 text-sm leading-7 text-slate-600">
            <p>Single-admin usage, no local auth, fake seeded data first.</p>
            <p>Browser traffic flows only to FastAPI. The web app never touches Postgres directly.</p>
            <p>Unknown or missing team tags stay visible through the protected Unallocated team.</p>
            <div className="flex flex-wrap gap-2 pt-2">
              <StatusPill label="next.js" />
              <StatusPill label="fastapi" />
              <StatusPill label="postgres 16" />
              <StatusPill label="docker compose" />
            </div>
          </div>
        </Panel>

        <Panel title="Next implementation steps" subtitle="Pulled directly from the attached roadmap">
          <div className="space-y-3 rounded-[24px] bg-slate-900 p-5 text-sm leading-7 text-slate-200">
            <p>1. Replace demo sync with a Cost Explorer collector using a 14-day rolling upsert.</p>
            <p>2. Keep findings persisted in tables instead of recomputing them on every request.</p>
            <p>3. Move the working stack into k3d with a Helm chart and shared collector CronJob.</p>
            <p>4. Add Better Auth, GHCR publishing, monitoring, and Hetzner rollout assets.</p>
          </div>
        </Panel>
      </div>
    </div>
  );
}
