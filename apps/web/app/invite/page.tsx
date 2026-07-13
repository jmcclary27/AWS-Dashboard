"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { PageHeader, Panel } from "@/components/ui";
import { apiRequest } from "@/lib/api";

type AcceptedInvite = {
  workspace_id: number;
  role: "owner" | "editor" | "viewer";
};

export default function InvitePage() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const [status, setStatus] = useState<"ready" | "accepting" | "accepted" | "error">("ready");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("This invite link is incomplete. Ask the workspace owner for a new link.");
    }
  }, [token]);

  async function acceptInvite() {
    if (!token) return;
    setStatus("accepting");
    setMessage(null);
    try {
      const result = await apiRequest<AcceptedInvite>("/invites/accept", {
        method: "POST",
        body: JSON.stringify({ token })
      });
      setStatus("accepted");
      setMessage(`You now have ${result.role} access. Opening the workspace…`);
      window.setTimeout(() => {
        // Reload so the shared workspace list is re-read after acceptance;
        // the provider otherwise still holds the pre-invite /me response.
        window.location.assign(`/dashboard?workspace_id=${result.workspace_id}`);
      }, 700);
    } catch (error) {
      setStatus("error");
      setMessage(error instanceof Error ? error.message : "Unable to accept this invite.");
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6 pt-10">
      <PageHeader
        eyebrow="Workspace invite"
        title="Join a shared workspace"
        description="Invite links are single-use, expire after seven days, and only work for the verified email address chosen by the owner."
      />
      <Panel title="Confirm access" subtitle="You must already be signed in with the matching Cognito account.">
        {message ? <p className="rounded-2xl bg-slate-50 p-4 text-sm text-slate-700">{message}</p> : null}
        {status !== "accepted" ? (
          <button
            type="button"
            onClick={acceptInvite}
            disabled={!token || status === "accepting" || status === "error"}
            className="mt-5 rounded-full bg-blue-700 px-5 py-3 text-sm font-medium text-white disabled:bg-blue-300"
          >
            {status === "accepting" ? "Joining workspace…" : "Accept invite"}
          </button>
        ) : null}
      </Panel>
    </div>
  );
}
