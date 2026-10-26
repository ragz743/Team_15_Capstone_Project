import { Alert, Box, Button, Card, CardContent, Stack, TextField, Typography } from "@mui/material";
import { useState, type FormEvent } from "react";
import WsuLogo from "./WsuLogo";

type TokenGateProps = {
  error: string | null;
  checking: boolean;
  onSubmit: (token: string) => void;
};

/** Sign in with the admin token configured on the API server (AWN_ADMIN_TOKEN). */
export default function TokenGate({ error, checking, onSubmit }: TokenGateProps) {
  const [token, setToken] = useState("");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (token.trim()) onSubmit(token.trim());
  }

  return (
    <Box component="main" sx={{ minHeight: "100vh", display: "grid", placeItems: "center", p: 2 }}>
      <Card sx={{ width: "min(380px, 100%)" }}>
        <CardContent sx={{ p: 3 }}>
          <Stack component="form" spacing={2} onSubmit={handleSubmit} noValidate>
            <Box className="gate-mark">
              <WsuLogo />
            </Box>
            <Box>
              <Typography variant="h1" sx={{ fontSize: 20 }}>
                AgWeatherNet admin
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Sign in to view users, retrieval quality, spending, and performance.
              </Typography>
            </Box>
            <TextField
              id="admin-token"
              label="Admin token"
              type="password"
              autoComplete="current-password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              error={Boolean(error)}
              required
              fullWidth
              size="small"
            />
            {error && (
              <Alert severity="error" role="alert">
                {error}
              </Alert>
            )}
            <Button type="submit" variant="contained" size="large" disabled={checking}>
              {checking ? "Signing in…" : "Sign in"}
            </Button>
          </Stack>
        </CardContent>
      </Card>
    </Box>
  );
}
