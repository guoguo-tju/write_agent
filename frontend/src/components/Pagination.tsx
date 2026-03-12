import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { formatMessage, useLanguage } from "../i18n";
import "./Pagination.css";

interface PaginationProps {
  page: number;
  total: number;
  limit?: number;
  onPageChange: (page: number) => void;
  className?: string;
}

export const Pagination: React.FC<PaginationProps> = ({
  page,
  total,
  limit = 10,
  onPageChange,
  className = "",
}) => {
  const { text } = useLanguage();
  const commonText = text.common;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.min(Math.max(page, 1), totalPages);
  const isPrevDisabled = currentPage <= 1;
  const isNextDisabled = currentPage >= totalPages;

  return (
    <div className={`app-pagination ${className}`.trim()}>
      <button
        type="button"
        onClick={() => onPageChange(currentPage - 1)}
        disabled={isPrevDisabled}
        aria-label={commonText.prevPage}
      >
        <ChevronLeft size={14} />
        {commonText.prevPage}
      </button>
      <span>
        {formatMessage(commonText.pageSummary, {
          current: currentPage,
          totalPages,
          total,
        })}
      </span>
      <button
        type="button"
        onClick={() => onPageChange(currentPage + 1)}
        disabled={isNextDisabled}
        aria-label={commonText.nextPage}
      >
        {commonText.nextPage}
        <ChevronRight size={14} />
      </button>
    </div>
  );
};
