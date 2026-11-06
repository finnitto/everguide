export default function Home() {
  return (
    <main>
      <header className="topbar">
        <a className="brand" href="/">everguide<span>.</span></a>
        <nav aria-label="Main navigation">
          <a href="#how-it-works">How it works</a>
          <a href="/admin">Administration</a>
        </nav>
      </header>
      <section className="hero">
        <div className="eyebrow">A clearer way to find funeral care</div>
        <h1>Find the right support,<br /><em>when it matters most.</em></h1>
        <p className="intro">Search and compare funeral directors across England. Clear information can help you take the next step with confidence.</p>
        <form className="search" action="/search" method="get">
          <label className="sr-only" htmlFor="location">Town, city or postcode</label>
          <input id="location" name="location" placeholder="Enter a town, city or postcode" />
          <button type="submit">Find funeral directors</button>
        </form>
        <p className="hint">The directory search experience is being built.</p>
      </section>
      <section className="principles" id="how-it-works">
        <article><div className="number">01</div><h2>Explore local options</h2><p>Find funeral service providers by location and discover the services they offer.</p></article>
        <article><div className="number">02</div><h2>Understand your choices</h2><p>Review provider information and available pricing in a clear, consistent format.</p></article>
        <article><div className="number">03</div><h2>Make an informed decision</h2><p>Use reliable, evidence-backed information to decide what is right for you.</p></article>
      </section>
      <footer><a className="brand" href="/">everguide<span>.</span></a><p>Clear information. Considered choices.</p><small>Everguide · Development preview</small></footer>
    </main>
  );
}
