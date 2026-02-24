import React, { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  PenTool,
  Palette,
  FolderOpen,
  CheckSquare,
  Image,
  Settings,
} from "lucide-react";
import "./Layout.css";

const navItems = [
  { to: "/", icon: PenTool, label: "写作改写" },
  { to: "/styles", icon: Palette, label: "风格管理" },
  { to: "/materials", icon: FolderOpen, label: "素材库" },
  { to: "/reviews", icon: CheckSquare, label: "审核" },
  { to: "/covers", icon: Image, label: "封面" },
];

export const Layout: React.FC = () => {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className="app-layout">
      <aside
        className={`sidebar ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}
      >
        <div className="logo">
          <div className="logo-icon">
            <PenTool size={20} />
          </div>
          {!sidebarCollapsed && <span className="logo-text">写作智能体</span>}
        </div>

        <nav className="sidebar-nav">
          <div className="sidebar-section">
            {!sidebarCollapsed && <div className="sidebar-label">功能</div>}
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `sidebar-item ${isActive ? "active" : ""}`
                }
              >
                <item.icon size={18} />
                {!sidebarCollapsed && <span>{item.label}</span>}
              </NavLink>
            ))}
          </div>
        </nav>

        <div className="sidebar-footer">
          <button
            className="sidebar-item"
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
          >
            <Settings size={18} />
            {!sidebarCollapsed && <span>设置</span>}
          </button>
        </div>
      </aside>

      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
};
