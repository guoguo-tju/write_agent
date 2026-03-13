import React, { useEffect, useMemo, useRef, useState } from "react";
import { AxiosError } from "axios";
import { CheckCircle2, Copy, Import, Loader2, Smartphone, Tablet, Monitor } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { AppTopNav } from "../components";
import { formatMessage, useLanguage } from "../i18n";
import {
  getCoverByRewrite,
  getRewrite,
  getRewritesPage,
  handleError,
  type CoverRecord,
  type RewriteRecord,
} from "../services/api";
import { handleSmartPaste } from "./layout/lib/htmlToMarkdown";
import { applyTheme, md, preprocessMarkdown } from "./layout/lib/markdown";
import { THEMES } from "./layout/lib/themes";
import { makeWeChatCompatible } from "./layout/lib/wechatCompat";
import "./LayoutPage.css";

type PreviewDevice = "mobile" | "tablet" | "pc";
type MessageTone = "info" | "success" | "warning" | "error";

const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const NORMALIZED_API_BASE_URL = API_BASE_URL.replace(/\/+$/, "");
const IMAGE_PLACEHOLDER_REGEX = /\[配图建议\|[^\]]+\]/g;
const HISTORY_LIMIT = 50;

const parseRewriteId = (value: string | null): number | null => {
  if (!value) {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return parsed;
};

const summarize = (value: string, maxLength = 60) => {
  const compact = value.replace(/\s+/g, " ").trim();
  if (compact.length <= maxLength) {
    return compact;
  }
  return `${compact.slice(0, maxLength)}...`;
};

const resolveImageUrl = (imageUrl?: string | null): string => {
  if (!imageUrl) {
    return "";
  }
  if (/^https?:\/\//i.test(imageUrl)) {
    return imageUrl;
  }
  if (imageUrl.startsWith("/")) {
    return `${NORMALIZED_API_BASE_URL}${imageUrl}`;
  }
  return `${NORMALIZED_API_BASE_URL}/${imageUrl}`;
};

const cleanRewriteContent = (raw: string) =>
  raw
    .replace(IMAGE_PLACEHOLDER_REGEX, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

const toMessage = (
  template: string,
  vars: Record<string, string | number> = {},
) => formatMessage(template, vars);

export const LayoutPage: React.FC = () => {
  const { text } = useLanguage();
  const layoutText = text.layout;
  const [searchParams, setSearchParams] = useSearchParams();
  const rewriteIdFromQuery = parseRewriteId(searchParams.get("rewrite_id"));

  const [markdownInput, setMarkdownInput] = useState("");
  const [renderedHtml, setRenderedHtml] = useState("");
  const [activeTheme, setActiveTheme] = useState("wechat");
  const [previewDevice, setPreviewDevice] = useState<PreviewDevice>("pc");

  const [isCopying, setIsCopying] = useState(false);
  const [copied, setCopied] = useState(false);

  const [rewriteOptions, setRewriteOptions] = useState<RewriteRecord[]>([]);
  const [selectedRewriteId, setSelectedRewriteId] = useState<number | "">("");
  const [isSeedLoading, setIsSeedLoading] = useState(false);
  const [seedMessage, setSeedMessage] = useState("");
  const [seedMessageTone, setSeedMessageTone] = useState<MessageTone>("info");

  const previewRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const rawHtml = md.render(preprocessMarkdown(markdownInput));
    const themedHtml = applyTheme(rawHtml, activeTheme);
    setRenderedHtml(themedHtml);
  }, [activeTheme, markdownInput]);

  useEffect(() => {
    void loadRewriteOptions();
  }, []);

  useEffect(() => {
    if (!rewriteIdFromQuery) {
      return;
    }
    void loadSeedFromRewrite(rewriteIdFromQuery);
  }, [rewriteIdFromQuery]);

  const loadRewriteOptions = async () => {
    try {
      const response = await getRewritesPage({
        page: 1,
        limit: HISTORY_LIMIT,
      });
      const completed = response.items.filter(
        (item) => item.status === "completed" && (item.final_content || item.source_article),
      );
      setRewriteOptions(completed);

      if (!rewriteIdFromQuery && completed.length > 0) {
        setSelectedRewriteId(completed[0].id);
      }
    } catch (error) {
      setSeedMessageTone("error");
      setSeedMessage(`${layoutText.loadListFailed}: ${handleError(error)}`);
    }
  };

  const fetchCoverByRewriteOrNull = async (
    rewriteId: number,
  ): Promise<CoverRecord | null> => {
    try {
      return await getCoverByRewrite(rewriteId);
    } catch (error) {
      if (error instanceof AxiosError && error.response?.status === 404) {
        return null;
      }
      throw error;
    }
  };

  const loadSeedFromRewrite = async (rewriteId: number) => {
    setIsSeedLoading(true);
    setSeedMessageTone("info");
    setSeedMessage(layoutText.loadingSeed);
    try {
      const [rewrite, cover] = await Promise.all([
        getRewrite(rewriteId),
        fetchCoverByRewriteOrNull(rewriteId),
      ]);

      const rawContent = rewrite.final_content || rewrite.source_article || "";
      const cleanedContent = cleanRewriteContent(rawContent);
      const coverUrl = resolveImageUrl(cover?.image_url);
      const nextMarkdown = coverUrl
        ? `![${layoutText.coverImageAlt}](${coverUrl})\n\n${cleanedContent}`
        : cleanedContent;

      setMarkdownInput(nextMarkdown);
      setSelectedRewriteId(rewriteId);

      if (coverUrl) {
        setSeedMessageTone("success");
        setSeedMessage(
          toMessage(layoutText.seedLoadedWithCover, { id: rewriteId }),
        );
      } else {
        setSeedMessageTone("warning");
        setSeedMessage(layoutText.seedLoadedNoCover);
      }
    } catch (error) {
      setSeedMessageTone("error");
      setSeedMessage(`${layoutText.loadSeedFailed}: ${handleError(error)}`);
    } finally {
      setIsSeedLoading(false);
    }
  };

  const selectedRewrite = useMemo(
    () => rewriteOptions.find((item) => item.id === selectedRewriteId) || null,
    [rewriteOptions, selectedRewriteId],
  );

  const syncRewriteQuery = (rewriteId: number | null) => {
    const next = new URLSearchParams(searchParams);
    if (rewriteId) {
      next.set("rewrite_id", String(rewriteId));
    } else {
      next.delete("rewrite_id");
    }
    setSearchParams(next, { replace: true });
  };

  const handleImportSeed = () => {
    if (!selectedRewriteId) {
      return;
    }
    syncRewriteQuery(selectedRewriteId);
  };

  const handleCopyWechat = async () => {
    if (!renderedHtml.trim()) {
      return;
    }

    setIsCopying(true);
    try {
      const htmlForWechat = await makeWeChatCompatible(renderedHtml, activeTheme);
      const plainText = previewRef.current?.innerText || markdownInput;

      if ("ClipboardItem" in window && navigator.clipboard.write) {
        const htmlBlob = new Blob([htmlForWechat], { type: "text/html" });
        const textBlob = new Blob([plainText], { type: "text/plain" });
        const clipboardItem = new ClipboardItem({
          "text/html": htmlBlob,
          "text/plain": textBlob,
        });
        await navigator.clipboard.write([clipboardItem]);
      } else {
        await navigator.clipboard.writeText(plainText);
      }

      setCopied(true);
      setSeedMessageTone("success");
      setSeedMessage(layoutText.copySuccess);
      window.setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      try {
        await navigator.clipboard.writeText(previewRef.current?.innerText || markdownInput);
        setSeedMessageTone("warning");
        setSeedMessage(layoutText.copyFallback);
      } catch {
        setSeedMessageTone("error");
        setSeedMessage(`${layoutText.copyFailed}: ${handleError(error)}`);
      }
    } finally {
      setIsCopying(false);
    }
  };

  const handlePasteError = () => {
    setSeedMessageTone("warning");
    setSeedMessage(layoutText.pasteImageFailed);
  };

  const layoutRewriteId = rewriteIdFromQuery || (selectedRewrite ? selectedRewrite.id : null);

  return (
    <div className="layout-v2-page">
      <AppTopNav />

      <main className="layout-v2-main">
        <section className="layout-v2-header">
          <div className="layout-v2-title">
            <h1>{layoutText.title}</h1>
            <p>{layoutText.subtitle}</p>
          </div>

          <div className="layout-v2-tools">
            <label className="layout-v2-field">
              <span>{layoutText.themeLabel}</span>
              <select
                value={activeTheme}
                onChange={(event) => setActiveTheme(event.target.value)}
              >
                {THEMES.map((theme) => (
                  <option key={theme.id} value={theme.id}>
                    {theme.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="layout-v2-field layout-v2-history-select">
              <span>{layoutText.importFromHistory}</span>
              <select
                value={selectedRewriteId}
                onChange={(event) =>
                  setSelectedRewriteId(
                    event.target.value ? Number(event.target.value) : "",
                  )
                }
              >
                <option value="">{layoutText.chooseRewrite}</option>
                {rewriteOptions.map((item) => (
                  <option key={item.id} value={item.id}>
                    #{item.id} {summarize(item.source_article)}
                  </option>
                ))}
              </select>
            </label>

            <button
              type="button"
              className="layout-v2-btn"
              onClick={handleImportSeed}
              disabled={!selectedRewriteId || isSeedLoading}
            >
              {isSeedLoading ? <Loader2 size={14} className="spin" /> : <Import size={14} />}
              {layoutText.importButton}
            </button>

            <button
              type="button"
              className="layout-v2-btn primary"
              onClick={handleCopyWechat}
              disabled={isCopying || !markdownInput.trim()}
            >
              {isCopying ? (
                <Loader2 size={14} className="spin" />
              ) : copied ? (
                <CheckCircle2 size={14} />
              ) : (
                <Copy size={14} />
              )}
              {isCopying
                ? layoutText.copying
                : copied
                  ? layoutText.copied
                  : layoutText.copyWechat}
            </button>
          </div>
        </section>

        {seedMessage && (
          <section className={`layout-v2-message ${seedMessageTone}`}>
            <span>{seedMessage}</span>
            {seedMessageTone === "warning" && layoutRewriteId ? (
              <a href={`/covers?rewrite_id=${layoutRewriteId}`}>
                {layoutText.goToCovers}
              </a>
            ) : null}
          </section>
        )}

        <section className="layout-v2-workbench">
          <div className="layout-v2-editor">
            <div className="layout-v2-panel-head">
              <h2>{layoutText.editorTitle}</h2>
              <span>
                {layoutRewriteId
                  ? toMessage(layoutText.rewriteIdLabel, { id: layoutRewriteId })
                  : layoutText.manualMode}
              </span>
            </div>
            <textarea
              className="layout-v2-textarea"
              value={markdownInput}
              placeholder={layoutText.editorPlaceholder}
              onChange={(event) => setMarkdownInput(event.target.value)}
              onPaste={(event) => handleSmartPaste(event, setMarkdownInput, handlePasteError)}
            />
          </div>

          <div className="layout-v2-preview">
            <div className="layout-v2-panel-head">
              <h2>{layoutText.previewTitle}</h2>
              <div className="layout-v2-device-switch">
                <button
                  type="button"
                  className={previewDevice === "mobile" ? "active" : ""}
                  onClick={() => setPreviewDevice("mobile")}
                  aria-label={layoutText.mobile}
                >
                  <Smartphone size={14} />
                </button>
                <button
                  type="button"
                  className={previewDevice === "tablet" ? "active" : ""}
                  onClick={() => setPreviewDevice("tablet")}
                  aria-label={layoutText.tablet}
                >
                  <Tablet size={14} />
                </button>
                <button
                  type="button"
                  className={previewDevice === "pc" ? "active" : ""}
                  onClick={() => setPreviewDevice("pc")}
                  aria-label={layoutText.desktop}
                >
                  <Monitor size={14} />
                </button>
              </div>
            </div>

            <div className="layout-v2-preview-body">
              <div className={`layout-v2-preview-shell ${previewDevice}`}>
                <div
                  ref={previewRef}
                  className="layout-v2-preview-content"
                  dangerouslySetInnerHTML={{ __html: renderedHtml }}
                />
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
};
