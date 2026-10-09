import { ChevronLeft, ChevronRight } from "lucide-react";

import { formatNumber } from "@/lib/format";

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total ? page * pageSize + 1 : 0;
  const to = Math.min(total, (page + 1) * pageSize);
  return (
    <div className="flex items-center justify-end gap-2">
      <span className="tabular mr-2 text-xs text-ink-3">
        {formatNumber(from)}–{formatNumber(to)} of {formatNumber(total)}
      </span>
      <button type="button" className="btn btn-sm" aria-label="Previous page" disabled={page === 0} onClick={() => onPage(page - 1)}>
        <ChevronLeft className="size-4" aria-hidden />
      </button>
      <button
        type="button"
        className="btn btn-sm"
        aria-label="Next page"
        disabled={page + 1 >= pages}
        onClick={() => onPage(page + 1)}
      >
        <ChevronRight className="size-4" aria-hidden />
      </button>
    </div>
  );
}
