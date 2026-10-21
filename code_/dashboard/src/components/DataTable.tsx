import type { ReactNode } from "react";

export type Column = { key: string; label: string; numeric?: boolean };

type DataTableProps = {
  caption: string;
  columns: Column[];
  rows: Record<string, ReactNode>[];
  empty?: string;
};

/** Plain table: the accessible twin of every chart, and the form for many-column data. */
export default function DataTable({ caption, columns, rows, empty = "No data in this range." }: DataTableProps) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={c.numeric ? "numeric" : undefined}>
                {c.label}
              </th>
            ))}
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
