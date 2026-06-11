const navItems = [
  { key: "dashboard", label: "Dashboard" },
  { key: "opportunities", label: "Opportunities" },
  { key: "reviewQueue", label: "Review Queue" },
  { key: "scraper", label: "Scraper" },
  { key: "settings", label: "Settings" },
];

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
            aria-current={currentPage === item.key ? "page" : undefined}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <main className="page">{children}</main>
    </div>
  );
}
