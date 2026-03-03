import React from "react";
import { NavLink } from "react-router-dom";
import { PenTool } from "lucide-react";
import "./AppTopNav.css";

const NAV_ITEMS = [
  { to: "/", label: "改写" },
  { to: "/styles", label: "风格" },
  { to: "/materials", label: "素材" },
  { to: "/reviews", label: "审核" },
  { to: "/covers", label: "封面" },
] as const;

export const AppTopNav: React.FC = () => {
  return (
    <header className="app-top-nav">
      <div className="app-top-nav-brand">
        <div className="app-top-nav-logo">
          <PenTool size={16} />
        </div>
        <span>砚雀 (YanQue)</span>
      </div>

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
    </header>
  );
};
