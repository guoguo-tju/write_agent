import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
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
        aria-label="上一页"
      >
        <ChevronLeft size={14} />
        上一页
      </button>
      <span>
        第 {currentPage} / {totalPages} 页 · 共 {total} 条
      </span>
      <button
        type="button"
        onClick={() => onPageChange(currentPage + 1)}
        disabled={isNextDisabled}
        aria-label="下一页"
      >
        下一页
        <ChevronRight size={14} />
      </button>
    </div>
  );
};
