import { createTheme } from "@mui/material/styles";

/**
 * The dashboard's MUI theme: WSU crimson on the warm neutrals the AgWeatherNet chat app uses.
 *
 * When the dashboard moves into the AgWeatherNet website (which also uses MUI), replace this theme with the
 * site's own; components only read colors and shapes from the theme. Chart colors are separate (see the
 * --series-* variables in styles.css) because they were validated for colorblind safety.
 */
export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#981e32", dark: "#791628", light: "#f5e9ec", contrastText: "#fff" },
    // info doubles as the "within budget" meter color, so it uses the first chart series blue
    info: { main: "#2a78d6" },
    success: { main: "#0ca30c", dark: "#006300" },
    warning: { main: "#fab219", dark: "#7a5200" },
    error: { main: "#d03b3b", dark: "#b42f2f" },
    background: { default: "#f3f2f1", paper: "#fff" },
    text: { primary: "#29272a", secondary: "#5d585e", disabled: "#a29ea3" },
    divider: "#eee9eb",
  },
  shape: { borderRadius: 11 },
  typography: {
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    h1: { fontSize: 24, fontWeight: 650 },
    h2: { fontSize: 18, fontWeight: 650 },
    h3: { fontSize: 15, fontWeight: 650 },
    button: { textTransform: "none", fontWeight: 550 },
  },
  components: {
    MuiCard: {
      defaultProps: { variant: "outlined" },
      styleOverrides: { root: { borderRadius: 16, boxShadow: "0 3px 10px #3d163005" } },
    },
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiToggleButton: {
      styleOverrides: {
        root: {
          textTransform: "none",
          paddingBlock: 5,
          "&.Mui-selected, &.Mui-selected:hover": { backgroundColor: "#981e32", color: "#fff" },
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { borderColor: "#ebe8e9", whiteSpace: "nowrap" },
        head: { color: "#5d585e", fontWeight: 600 },
      },
    },
    MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
    MuiAlert: { styleOverrides: { root: { borderRadius: 11 } } },
  },
});
