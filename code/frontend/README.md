# AWN Frontend

Vite + React + TypeScript frontend mockup for the AG Weather Net chatbot.

## Current scope

- clean visual prototype for a non-technical audience
- no seeded weather data
- no fake assistant responses
- simple chat layout ready for backend wiring later

## Scripts

```bash
npm install
npm run dev
npm run build
npm run lint
```

## Integration note

The current backend repository does not expose a FastAPI chat route yet.
When that exists, the composer can be wired to the backend and the main
conversation area can render real answers
