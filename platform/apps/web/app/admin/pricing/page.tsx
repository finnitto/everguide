"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type PriceEvidence = {
  id: number;
  provider_id: number;
  branch_id?: number | null;
  service_category: string;
  service_name: string;
  fee_type: string;
  amount: string;
  amount_upper?: string | null;
  currency: string;
  price_basis: string;
  source_name: string;
  source_url: string;
  source_permission_id?: number | null;
  source_retrieved_at: string;
  evidence_sha256: string;
  evidence_excerpt?: string | null;
  evidence_payload?: {
    provenance?: {
      extraction_method?: string;
      verification_status?: string;
      model?: string;
      response_id?: string;
      extraction_confidence?: number;
      overture_candidate_id?: number;
      gers_id?: string;
      source_permission_id?: number;
    };
  };
  verification_label?: string;
};

function formatAmount(row: PriceEvidence) {
  const format = (value: string) =>
    new Intl.NumberFormat("en-GB", { style: "currency", currency: row.currency }).format(Number(value));
  if (row.price_basis === "from") return `From ${format(row.amount)}`;
  if (row.price_basis === "range" && row.amount_upper) return `${format(row.amount)}–${format(row.amount_upper)}`;
  return format(row.amount);
}

export default function PricingReviewPage() {
  const [token, setToken] = useState("");
  const [tokenInput, setTokenInput] = useState("");
  const [items, setItems] = useState<PriceEvidence[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const apiFetch = useCallback(async (url: string, init: RequestInit = {}) => {
    return fetch(url, {
      ...init,
      headers: {
        ...((init.headers || {}) as Record<string, string>),
        Authorization: `Bearer ${token}`,
      },
    });
  }, [token]);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const response = await apiFetch(`${API}/api/v1/evidence/pricing?review_status=pending&limit=500`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not load pending price evidence.");
      setItems(data.items || []);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load pending price evidence.");
    }
  }, [apiFetch, token]);

  useEffect(() => {
    if (token) void load();
  }, [load, token]);

  async function decide(row: PriceEvidence, decision: "approved" | "rejected") {
    setBusyId(row.id);
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(`${API}/api/v1/evidence/pricing/${row.id}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          review_status: decision,
          review_notes: decision === "approved"
            ? "Reviewed by an Everguide reviewer against the cited provider source."
            : "AI-extracted price was not verified against the cited provider source.",
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not save price decision.");
      setNotice(decision === "approved"
        ? `Price #${row.id} marked verified by Everguide.`
        : `Price #${row.id} rejected and removed from public display.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save price decision.");
    } finally {
      setBusyId(null);
    }
  }

  if (!token) {
    return (
      <main className="admin-shell">
        <header className="admin-header">
          <div>
            <p className="eyebrow">EVERGUIDE ADMIN</p>
            <h1>Price verification</h1>
            <p>Sign in with your reviewer bearer token to inspect AI-extracted prices and decide whether each amount is supported by its cited provider source.</p>
          </div>
          <Link className="secondary-button" href="/admin">Back to admin</Link>
        </header>
        {error && <div className="alert alert-error">{error}</div>}
        <section className="admin-card">
          <form onSubmit={(event) => { event.preventDefault(); setError(""); setToken(tokenInput.trim()); }}>
            <label htmlFor="price-review-token">Reviewer bearer token</label>
            <div className="provider-actions" style={{ marginTop: 10 }}>
              <input id="price-review-token" type="password" autoComplete="off" value={tokenInput}
                onChange={(event) => setTokenInput(event.target.value)} placeholder="Paste reviewer token"
                required style={{ flex: "1 1 320px", minWidth: 0, border: "1px solid #dfe4dd", borderRadius: 5, padding: 12 }} />
              <button className="primary-button" type="submit">Access price review</button>
            </div>
            <p className="admin-footnote">The token is held in page memory only and is not saved to browser storage.</p>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="admin-shell">
      <header className="admin-header">
        <div>
          <p className="eyebrow">EVERGUIDE ADMIN · PRICE EVIDENCE</p>
          <h1>Verify extracted prices</h1>
          <p>AI extraction is a research aid, not verification. Open the provider source and confirm the service, amount, price basis and any stated inclusions or exclusions before approving.</p>
        </div>
        <div className="provider-actions">
          <button className="secondary-button" onClick={() => void load()}>Refresh</button>
          <button className="secondary-button" onClick={() => { setToken(""); setTokenInput(""); setItems([]); }}>Sign out</button>
          <Link className="secondary-button" href="/admin">Back to admin</Link>
        </div>
      </header>
      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}
      <section className="admin-card">
        <div className="card-heading">
          <div>
            <h2>Pending AI-extracted prices</h2>
            <p>These records are visible to users with an explicit “AI-extracted · Not verified” label until you approve them.</p>
          </div>
          <span className="count-chip">{items.length} awaiting review</span>
        </div>
        {items.length === 0 ? (
          <div className="empty-state"><strong>No pending prices</strong><p>AI-extracted prices will appear here when approved candidates complete enrichment.</p></div>
        ) : (
          <div className="provider-list">
            {items.map((row) => {
              const provenance = row.evidence_payload?.provenance || {};
              return (
                <article className="provider-row price-review-row" key={row.id}>
                  <div className="provider-info">
                    <strong>{row.service_name}</strong>
                    <span>{formatAmount(row)} · {row.service_category.replace(/_/g, " ")} · {row.fee_type.replace(/_/g, " ")}</span>
                    <small>Provider #{row.provider_id} · Branch {row.branch_id ?? "provider-wide"} · Overture candidate #{provenance.overture_candidate_id ?? "not linked"} · GERS {provenance.gers_id ?? "not recorded"}</small>
                    <small>AI model {provenance.model || "not recorded"} · Confidence {typeof provenance.extraction_confidence === "number" ? `${Math.round(provenance.extraction_confidence * 100)}%` : "not supplied"} · Retrieved {new Date(row.source_retrieved_at).toLocaleString("en-GB")}</small>
                    <div className="review-note">
                      <strong>Source quotation</strong>
                      <p>“{row.evidence_excerpt || "No quotation supplied"}”</p>
                      <p><strong>Source:</strong> {row.source_name} · permission record #{row.source_permission_id ?? provenance.source_permission_id ?? "not recorded"}</p>
                      <p><strong>Source hash:</strong> {row.evidence_sha256}</p>
                      <a href={row.source_url} target="_blank" rel="noreferrer">Open cited provider price page ↗</a>
                    </div>
                  </div>
                  <div className="provider-actions price-review-actions">
                    <span className="status-pill status-needs_review">AI-extracted · Not verified</span>
                    <button className="primary-button" disabled={busyId === row.id} onClick={() => void decide(row, "approved")}>
                      {busyId === row.id ? "Saving…" : "Approve as verified"}
                    </button>
                    <button className="secondary-button" disabled={busyId === row.id} onClick={() => void decide(row, "rejected")}>Reject price</button>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
      <footer className="admin-footnote">Approval changes only this price evidence record. It does not alter provider identity, branch information or provider publication status.</footer>
    </main>
  );
}
