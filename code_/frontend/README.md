# AWN Frontend

Vite + React + TypeScript frontend mockup for the AG Weather Net chatbot.

## What it does

- Shows the chat UI.
- Sends chat messages to the FastAPI backend.
- Uses the Vite `/api` proxy so local requests go to `localhost:8000`.

## Scripts

```bash
npm install
npm run dev
npm run build
npm run lint
```

## Running locally

Start the backend from the repo root:

```bash
uvicorn backend.api:app --reload --port 8000
```

Then start the frontend from this folder:

```bash
npm install
npm run dev
```

Open `http://localhost:5173` in the browser.

## Map selection and saved chats

Choose a map point to request weather. Only the selected point is plotted.
Reopening a saved chat restores its point. A new map selection is sent as a location
override until the server accepts it. Other messages use the saved context, so reusing
an old location can update the map. Retrying a failed message sends its original input
even if the map has changed. History recall can run without a selected point.
The browser loads OpenStreetMap tiles through Leaflet.

The workspace composes the sidebar, transcript, map and composer. Conversation state
uses a reducer. Separate hooks handle history navigation and message submission.
Request ownership prevents responses from an earlier chat from updating the active chat.

The client separates endpoint calls in `api.ts`, HTTP handling in `http.ts` and response
types and validation in `apiContracts.ts`. Chat submission and history navigation share
request handling while keeping their existing cancellation and retry behavior.

## Response formatting

Assistant replies render Markdown, including lists, links and scrollable tables.
User messages keep their original whitespace. Raw HTML and images are disabled;
links use the renderer's default URL protections. The final-answer prompt requests
paragraphs for simple answers, bullets for measurements and tables for comparisons.
Saved replies keep their original text.

With Vite running and Playwright/Chrome available, run the browser check from the
repository root:

```bash
AWN_UI_URL=http://127.0.0.1:5173 node testing/browser_markdown.cjs
```

The check mocks API responses and covers fresh/saved replies, unsafe HTML and links,
source details, user whitespace and desktop/mobile layouts.
