import React from "react";
import { NavLink } from "react-router-dom";
import { PenTool } from "lucide-react";
import { useLanguage } from "../i18n";
import "./AppTopNav.css";

export const AppTopNav: React.FC = () => {
  const { lang, setLang, text } = useLanguage();
  const NAV_ITEMS = [
    { to: "/", label: text.nav.links.rewrite },
    { to: "/styles", label: text.nav.links.styles },
    { to: "/materials", label: text.nav.links.materials },
    { to: "/reviews", label: text.nav.links.reviews },
    { to: "/covers", label: text.nav.links.covers },
    { to: "/layout", label: text.nav.links.layout },
  ] as const;

  return (
    <div className="app-top-shell">
      <header className="app-top-nav">
        <div className="app-top-nav-brand">
          <div className="app-top-nav-logo">
            <PenTool size={16} />
          </div>
          <span>砚雀 (YanQue)</span>
        </div>

        <div className="app-top-nav-right">
          <nav className="app-top-nav-links">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `app-top-nav-item${isActive ? " active" : ""}`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div
            className="app-top-nav-lang"
            role="group"
            aria-label={text.nav.languageLabel}
          >
            <button
              type="button"
              className={lang === "zh" ? "active" : ""}
              onClick={() => setLang("zh")}
            >
              CN
            </button>
            <button
              type="button"
              className={lang === "en" ? "active" : ""}
              onClick={() => setLang("en")}
            >
              EN
            </button>
          </div>
        </div>
      </header>
    </div>
  );
};
