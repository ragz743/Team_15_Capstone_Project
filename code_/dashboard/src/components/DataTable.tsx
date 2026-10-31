import { Table, TableBody, TableCell, TableContainer, TableHead, TableRow, TableSortLabel } from "@mui/material";
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
  /** Cap the height and scroll inside the table (used for chart table views). */
  maxHeight?: number;
};

/** MUI table: the accessible twin of every chart, and the form for many-column data. */
export default function DataTable({ caption, columns, rows, empty = "No data in this range.", sort, onSort, maxHeight }: DataTableProps) {
  return (
    <TableContainer sx={maxHeight ? { maxHeight } : undefined}>
      <Table size="small" stickyHeader={Boolean(maxHeight)} aria-label={caption}>
        <TableHead>
          <TableRow>
            {columns.map((c) => {
              const active = sort?.key === c.key;
              return (
                <TableCell
                  key={c.key}
                  align={c.numeric ? "right" : "left"}
                  sortDirection={c.sortable && onSort ? (active ? sort.direction : false) : undefined}
                >
                  {c.sortable && onSort ? (
                    <TableSortLabel active={active} direction={active ? sort.direction : "asc"} onClick={() => onSort(c.key)}>
                      {c.label}
                    </TableSortLabel>
                  ) : (
                    c.label
                  )}
                </TableCell>
              );
            })}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={columns.length} align="center" sx={{ color: "text.secondary", py: 3 }}>
                {empty}
              </TableCell>
            </TableRow>
          ) : (
            rows.map((row, i) => (
              <TableRow key={i} hover>
                {columns.map((c) => (
                  <TableCell key={c.key} align={c.numeric ? "right" : "left"} sx={c.numeric ? { fontVariantNumeric: "tabular-nums" } : undefined}>
                    {row[c.key]}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
