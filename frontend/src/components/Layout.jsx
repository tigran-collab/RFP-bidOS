const navItems = [
  { key: "dashboard", label: "Dashboard" },
  { key: "opportunities", label: "Opportunities" },
  { key: "scraper", label: "Scraper" },
  { key: "settings", label: "Settings" },
];

export default function Layout({ children, currentPage, onNavigate }) {
  return (
    <div>
      <nav>
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
      <main>{children}</main>
    </div>
  );
}
