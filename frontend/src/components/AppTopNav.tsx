import React, { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { ChevronDown, PenTool } from "lucide-react";
import { useLanguage } from "../i18n";
import "./AppTopNav.css";

export const AppTopNav: React.FC = () => {
  const { lang, setLang, text } = useLanguage();
  const location = useLocation();
  const navigate = useNavigate();
  const marketRef = useRef<HTMLDivElement | null>(null);
  const closeTimerRef = useRef<number | null>(null);
  const [isMarketOpen, setIsMarketOpen] = useState(false);
  const marketItems = useMemo(
    () => [
      { to: "/github-trends", label: text.nav.links.githubTrends },
      { to: "/linuxdo-trends", label: text.nav.links.linuxdoTrends },
    ],
    [text.nav.links.githubTrends, text.nav.links.linuxdoTrends],
  );
  const isMarketActive = marketItems.some((item) =>
    location.pathname.startsWith(item.to),
  );

  useEffect(() => {
    return () => {
      if (closeTimerRef.current !== null) {
        window.clearTimeout(closeTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!marketRef.current) {
        return;
      }
      if (!marketRef.current.contains(event.target as Node)) {
        setIsMarketOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsMarketOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
    };
  }, []);

  useEffect(() => {
    setIsMarketOpen(false);
  }, [location.pathname]);

  const isMobileViewport = () => window.matchMedia("(max-width: 860px)").matches;

  const openMarketMenu = () => {
    if (isMobileViewport()) {
      return;
    }
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
    setIsMarketOpen(true);
  };

  const closeMarketMenuWithDelay = () => {
    if (isMobileViewport()) {
      return;
    }
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
    }
    closeTimerRef.current = window.setTimeout(() => {
      setIsMarketOpen(false);
      closeTimerRef.current = null;
    }, 140);
  };

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
        <div className="app-top-nav-left">
          <div className="app-top-nav-brand">
            <div className="app-top-nav-logo">
              <PenTool size={16} />
            </div>
            <span>砚雀 (YanQue)</span>
          </div>

          <div
            className={`app-top-nav-market${isMarketOpen ? " open" : ""}${isMarketActive ? " active" : ""}`}
            ref={marketRef}
            onMouseEnter={openMarketMenu}
            onMouseLeave={closeMarketMenuWithDelay}
          >
            <button
              type="button"
              className={`app-top-nav-market-trigger${isMarketActive ? " active" : ""}`}
              aria-haspopup="menu"
              aria-expanded={isMarketOpen}
              onClick={() => {
                if (isMobileViewport()) {
                  setIsMarketOpen((value) => !value);
                  return;
                }
                setIsMarketOpen(false);
                navigate("/github-trends");
              }}
            >
              <span>{text.nav.links.hotMarket}</span>
              <ChevronDown size={14} />
            </button>

            <div className="app-top-nav-market-menu" role="menu" aria-label={text.nav.links.hotMarket}>
              {marketItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `app-top-nav-market-link${isActive ? " active" : ""}`
                  }
                  role="menuitem"
                >
                  {item.label}
                </NavLink>
              ))}
            </div>
          </div>
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
