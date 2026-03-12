import React, { useEffect, useMemo, useState } from "react";
import { LanguageContext, type LanguageContextValue } from "./context";
import { LANGUAGE_STORAGE_KEY, messages, type Language } from "./messages";

function getInitialLanguage(): Language {
  if (typeof window === "undefined") {
    return "zh";
  }

  const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
  if (stored === "zh" || stored === "en") {
    return stored;
  }

  return "zh";
}

export const LanguageProvider: React.FC<React.PropsWithChildren> = ({ children }) => {
  const [lang, setLang] = useState<Language>(() => getInitialLanguage());

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
  }, [lang]);

  const value = useMemo<LanguageContextValue>(() => ({
    lang,
    setLang,
    text: messages[lang],
  }), [lang]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
};
