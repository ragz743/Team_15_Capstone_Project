import type { ReactNode } from "react";

export type Column = {
  key: string;
  label: string;
  numeric?: boolean;
  /** Set to make the column sortable by clicking its header. */
  sortable?: boolean;
};

export type SortState = { key: string; direction: "asc" | "desc" };

type DataTableProps = {
  caption: string;
  columns: Column[];
  rows: Record<string, ReactNode>[];
  empty?: string;
  /** The column currently sorted, shown with an arrow and announced via aria-sort. */
  sort?: SortState;
  onSort?: (key: string) => void;
};

/** Plain table: the accessible twin of every chart, and the form for many-column data. */
export default function DataTable({ caption, columns, rows, empty = "No data in this range.", sort, onSort }: DataTableProps) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key;
              const sortable = c.sortable && onSort;
              return (
                <th
                  key={c.key}
                  scope="col"
                  className={c.numeric ? "numeric" : undefined}
                  aria-sort={sortable ? (active ? (sort.direction === "asc" ? "ascending" : "descending") : "none") : undefined}
                >
                  {sortable ? (
                    <button type="button" className={active ? "sort-button is-sorted" : "sort-button"} onClick={() => onSort(c.key)}>
                      {c.label}
                      <span className="sort-indicator" aria-hidden="true">
                        {active ? (sort.direction === "asc" ? "↑" : "↓") : "↕"}
                      </span>
                    </button>
                  ) : (
                    c.label
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="empty-cell">
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c.key} className={c.numeric ? "numeric" : undefined}>
                    {row[c.key]}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
