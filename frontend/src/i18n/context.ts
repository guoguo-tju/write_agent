import { createContext } from "react";
import type { Language, MessageSchema } from "./messages";

export type LanguageContextValue = {
  lang: Language;
  setLang: (lang: Language) => void;
  text: MessageSchema;
};

export const LanguageContext = createContext<LanguageContextValue | undefined>(undefined);
