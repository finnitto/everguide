"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type Result = {
  provider_name: string;
  branch_name: string;
  address_line_1: string;
  town_city: string;
  postcode: string;
  telephone?: string;
  website?: string;
  services: string[];
};

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
            <div>
              <div className="eyebrow">FUNERAL DIRECTOR</div>
              <h2>{result.branch_name}</h2>
              <p>{result.provider_name}</p>
              <span>{result.address_line_1}, {result.town_city}, {result.postcode}</span>
              {result.telephone && <span>{result.telephone}</span>}
            </div>
            {result.website && <a href={result.website} target="_blank" rel="noreferrer">Visit website ↗</a>}
          </article>
        ))}
      </section>
      <footer><Link className="brand" href="/">everguide<span>.</span></Link><small>Clear information. Considered choices.</small></footer>
    </main>
  );
}
