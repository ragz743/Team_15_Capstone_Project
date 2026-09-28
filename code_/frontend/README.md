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


## Map selection

Choose a point before sending a weather question. Click the map or move it with the
arrow keys and select Use map center. The marker represents the requested point;
source station coordinates stay on the server. New conversation clears the point.

`POST /api/chat` now sends `messages` and `point: {latitude, longitude}`. Deploy this
client with the matching backend. Source selection and date validation happen there.
