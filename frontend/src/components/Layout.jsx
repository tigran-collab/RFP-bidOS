const navItems = [
  { key: "dashboard", label: "Dashboard" },
  { key: "opportunities", label: "Opportunities" },
  { key: "newOpportunity", label: "New Opportunity" },
  { key: "reviewQueue", label: "Review Queue" },
  { key: "archived", label: "Archived" },
  { key: "scraper", label: "Scraper" },
  { key: "portals", label: "Portals" },
  { key: "kbDashboard", label: "Knowledge Base" },
  { key: "settings", label: "Settings" },
];

// Any kb* route highlights the Knowledge Base nav entry.
function isActive(itemKey, currentPage) {
  if (itemKey === "kbDashboard") {
    return currentPage.startsWith("kb");
  }
  return currentPage === itemKey;
}

export default function Layout({ children, currentPage, onNavigate }) {
  return (
    <div className="app-shell">
      <nav className="top-nav">
        <div className="brand">RFP BidOS</div>
        {navItems.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => onNavigate(item.key)}
            aria-current={isActive(item.key, currentPage) ? "page" : undefined}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <main className="page" key={currentPage}>
        {children}
      </main>
    </div>
  );
}
