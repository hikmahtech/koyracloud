import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listAllowedUsers, addAllowedUser, removeAllowedUser } from "../api";

export default function Team() {
  const qc = useQueryClient();
  const { data, isLoading, isError } = useQuery({ queryKey: ["allowed-users"], queryFn: listAllowedUsers });
  const [login, setLogin] = useState("");
  const inval = () => qc.invalidateQueries({ queryKey: ["allowed-users"] });
  const addMut = useMutation({ mutationFn: () => addAllowedUser(login), onSuccess: () => { setLogin(""); inval(); } });
  const delMut = useMutation({ mutationFn: (l) => removeAllowedUser(l), onSuccess: inval });

  if (isLoading) return <p className="mono text-[var(--color-muted)]">loading…</p>;
  if (isError) return <p className="text-[var(--color-danger)]">Admins only.</p>;

  return (
    <div className="max-w-2xl">
      <Link to="/" className="mono text-xs text-[var(--color-muted)] hover:text-[var(--color-fg)] no-underline">← apps</Link>
      <div className="eyebrow mt-4">Access</div>
      <h1 className="font-display text-3xl mt-2 mb-1">Team</h1>
      <p className="text-sm text-[var(--color-muted)] mb-8">
        Anyone allowed here can sign in and deploy apps — which run code on your swarm.
        Invite only people you trust. <span className="text-[var(--color-fg)]">Admins see and
        manage every app; invited members only see the apps they create.</span> To give a
        teammate their own private workspace, invite them as a member below — don't add them
        to <span className="text-acid mono">KOYRA_ALLOWED_LOGINS</span>.
      </p>

      {/* Admins */}
      <section className="mb-8">
        <div className="flex items-center gap-2 mb-3">
          <h2 className="font-display text-lg">Admins</h2>
          <span className="mono text-[10px] text-acid border border-[var(--color-line)] rounded px-1.5 py-0.5">ENV · MANAGE ACCESS</span>
        </div>
        <div className="card divide-y divide-[var(--color-line)]">
          {(data.admins || []).map((a) => (
            <div key={a} className="flex items-center justify-between px-4 py-3">
              <span className="mono text-sm">@{a}</span>
              <span className="mono text-xs text-[var(--color-muted)]">admin</span>
            </div>
          ))}
          {(data.admins || []).length === 0 && <div className="px-4 py-3 mono text-sm text-[var(--color-muted)]">None configured.</div>}
        </div>
        <p className="mono text-[11px] text-[var(--color-muted)] mt-2">
          Admins come from <span className="text-acid">KOYRA_ALLOWED_LOGINS</span> and can't be
          changed here. They see and manage <span className="text-[var(--color-fg)]">every</span> app.
        </p>
      </section>

      {/* Invited members */}
      <section>
        <h2 className="font-display text-lg mb-3">Invited members</h2>
        <div className="card divide-y divide-[var(--color-line)]">
          {(data.members || []).map((m) => (
            <div key={m.login} className="flex items-center justify-between px-4 py-3">
              <span className="mono text-sm">@{m.login}</span>
              <div className="flex items-center gap-3">
                {m.added_by && <span className="mono text-xs text-[var(--color-muted)]">invited by @{m.added_by}</span>}
                <button onClick={() => delMut.mutate(m.login)} className="text-xs text-[var(--color-danger)] hover:underline bg-transparent border-0 cursor-pointer">remove</button>
              </div>
            </div>
          ))}
          {(data.members || []).length === 0 && <div className="px-4 py-3 mono text-sm text-[var(--color-muted)]">No invited members yet.</div>}
        </div>
        <p className="mono text-[11px] text-[var(--color-muted)] mt-2">
          Members get a private workspace: they only see and manage the apps they create, never each other's.
        </p>
        <form onSubmit={(e) => { e.preventDefault(); addMut.mutate(); }} className="flex gap-2 mt-4">
          <input value={login} onChange={(e) => setLogin(e.target.value)} placeholder="github-login" className="input mono" />
          <button disabled={!login || addMut.isPending} className="btn btn-primary shrink-0">Invite</button>
        </form>
        {addMut.isError && <p className="text-[var(--color-danger)] text-sm mt-2">{addMut.error?.response?.data?.detail || "Failed"}</p>}
      </section>
    </div>
  );
}
