type SearchPageProps = { searchParams: Promise<{ location?: string }> };

export default async function SearchPage({ searchParams }: SearchPageProps) {
  const { location } = await searchParams;
  return (
    <main className="admin-page">
      <a className="brand" href="/">everguide<span>.</span></a>
      <div className="admin-panel">
        <div className="eyebrow">Directory search</div>
        <h1>Search is coming soon</h1>
        <p>
          {location ? `Your search location: ${location}. ` : ""}
          Location-based provider search will be introduced in a subsequent release.
        </p>
        <a className="back-link" href="/">← Return to homepage</a>
      </div>
    </main>
  );
}
