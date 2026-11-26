"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Price = {
  id: number;
  service_category: string;
  service_name: string;
  option_group_id?: string | null;
  option_group_name?: string | null;
  fee_type: string;
  amount: string;
  amount_upper?: string | null;
  currency: string;
  price_basis: "fixed" | "from" | "range";
  includes: string[];
  excludes: string[];
  source_name: string;
  source_url: string;
  source_retrieved_at: string;
  verification_status: "verified" | "unverified";
  verification_label: string;
  extraction_method: string;
};

type Result = {
  provider_name: string;
  branch_name: string;
  address_line_1: string;
  town_city: string;
  postcode: string;
  telephone?: string;
  website?: string;
  services: string[];
  prices?: Price[];
};

function formatGBP(value: string, currency: string) {
  return new Intl.NumberFormat("en-GB", { style: "currency", currency }).format(Number(value));
}

function displayPrice(price: Price) {
  const lower = formatGBP(price.amount, price.currency);
  if (price.price_basis === "from") return `From ${lower}`;
  if (price.price_basis === "range" && price.amount_upper) {
    return `${lower}–${formatGBP(price.amount_upper, price.currency)}`;
  }
  return lower;
}

function groupPrices(prices: Price[]) {
  const groups = new Map<string, { label: string; prices: Price[] }>();
  for (const price of prices) {
    const key = price.option_group_id || `price:${price.id}`;
    const label = price.option_group_name || "Other price information";
    const group = groups.get(key) || { label, prices: [] };
    group.prices.push(price);
    groups.set(key, group);
  }
  return [...groups.entries()].map(([key, group]) => ({ key, ...group }));
}

export default function SearchPage() {
  const [term, setTerm] = useState("");
  const [results, setResults] = useState<Result[]>([]);
  const [searched, setSearched] = useState(false);
  const [error, setError] = useState("");

  async function search(value = term) {
    setSearched(true);
    setError("");
    if (value.trim().length < 2) {
      setResults([]);
      return;
    }
    try {
      const response = await fetch(
        `${API}/api/v1/directory/search?q=${encodeURIComponent(value)}`
      );
      if (!response.ok) throw new Error("Search request failed");
      const data = await response.json();
      setResults(data.items || []);
    } catch {
      setError("Search is temporarily unavailable. Please try again.");
      setResults([]);
    }
  }

  useEffect(() => {
    const initial = new URLSearchParams(window.location.search).get("location");
    if (!initial) return;

    setTerm(initial);
    setSearched(true);
    void (async () => {
      setError("");
      try {
        const response = await fetch(
          `${API}/api/v1/directory/search?q=${encodeURIComponent(initial)}`
        );
        if (!response.ok) throw new Error("Search request failed");
        const data = await response.json();
        setResults(data.items || []);
      } catch {
        setError("Search is temporarily unavailable. Please try again.");
        setResults([]);
      }
    })();
  }, []);

  return (
    <main>
      <header className="topbar">
        <Link className="brand" href="/">everguide<span>.</span></Link>
        <nav><Link href="/">Home</Link><Link href="/admin">Administration</Link></nav>
      </header>
      <section className="results-wrap">
        <div className="eyebrow">THE EVERGUIDE DIRECTORY</div>
        <h1>Find funeral directors</h1>
        <p className="results-intro">Search by provider name, town, city or postcode.</p>
        <form className="search results-search" onSubmit={(event) => { event.preventDefault(); void search(); }}>
          <input
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder="Enter a town, city or postcode"
            aria-label="Search location"
          />
          <button type="submit">Search directory</button>
        </form>
        {error && <p className="search-error">{error}</p>}
        {searched && (
          <div className="result-heading">
            <h2>Search results</h2>
            <span>{results.length} published {results.length === 1 ? "branch" : "branches"}</span>
          </div>
        )}
        {searched && results.length === 0 && !error && (
          <div className="empty-state public-empty">
            <strong>No published providers found</strong>
            <p>Try another town, provider name or postcode. Only approved and published records appear here.</p>
          </div>
        )}
        {results.map((result, index) => (
          <article className="public-result" key={`${result.provider_name}-${index}`}>
            <div className="public-provider">
              <div className="eyebrow">FUNERAL DIRECTOR</div>
              <h2>{result.branch_name}</h2>
              <p>{result.provider_name}</p>
              <span>{result.address_line_1}, {result.town_city}, {result.postcode}</span>
              {result.telephone && <span>{result.telephone}</span>}
              {result.website && <a href={result.website} target="_blank" rel="noreferrer">Visit website ↗</a>}
            </div>
            {result.prices && result.prices.length > 0 && (
              <section className="public-prices" aria-label="Published price information">
                <h3>Price information</h3>
                {groupPrices(result.prices).map((group) => (
                  <div className="public-price-group" key={group.key}>
                    {group.prices[0]?.option_group_id && <h4>{group.label}</h4>}
                    {group.prices.map((price) => (
                  <div className="public-price" key={price.id}>
                    <div className="public-price-main">
                      <strong>{price.service_name}</strong>
                      <span className="public-price-amount">{displayPrice(price)}</span>
                    </div>
                        <span className="price-detail">
                          {price.fee_type === "package" ? "Package price" : price.fee_type.replace(/_/g, " ")}
                        </span>
                    <span className={`price-verification ${price.verification_status === "verified" ? "price-verified" : "price-unverified"}`}>
                      {price.verification_label}
                    </span>
                    <p className="price-source">
                      Source: <a href={price.source_url} target="_blank" rel="noreferrer">{price.source_name} website ↗</a>
                      {" · "}retrieved {new Date(price.source_retrieved_at).toLocaleDateString("en-GB")}
                    </p>
                    {price.includes.length > 0 && <p className="price-detail">Includes: {price.includes.join(", ")}</p>}
                    {price.excludes.length > 0 && <p className="price-detail">Excludes: {price.excludes.join(", ")}</p>}
                  </div>
                    ))}
                  </div>
                ))}
                <p className="price-disclosure">
                  Automatically extracted prices have not been checked by an Everguide reviewer. They are shown for guidance only;
                  confirm the latest price, what is included and any additional fees directly with the provider.
                  Prices labelled verified have been reviewed by Everguide against their cited source. Components are
                  shown as listed by the provider and are not added to package prices.
                </p>
              </section>
            )}
          </article>
        ))}
      </section>
      <footer><Link className="brand" href="/">everguide<span>.</span></Link><small>Clear information. Considered choices.</small></footer>
    </main>
  );
}
