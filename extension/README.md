# Signal Check browser extension (Chrome)

Check part of any web page without opening the app. Right-click selected text, an image, or
drag a box around a post; the result card opens in Chrome's side panel. The extension is a thin
client for the backend's `POST /check` endpoint and runs no analysis itself.

## Build and install

Requires Node.js 20 or newer and the backend running on `http://127.0.0.1:8000`
(see the [Quickstart](../README-QUICKSTART.md)).

```bash
cd extension
npm install
npm run build
```

Then in Chrome open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**,
and choose the `extension/dist` folder. After every `npm run build`, click the reload icon on
the extension's card.

## Use

- **Selected text**: highlight text, right-click, choose **Check selected text with Signal**. The
  text is sent as the caption and the page address as the source.
- **An image**: right-click it, choose **Check this image with Signal**. The original file is
  fetched when the image host allows it; otherwise the visible part of the image is captured
  from a screenshot of the tab.
- **A region**: right-click anywhere, choose **Check a region of this page with Signal**, then
  drag a rectangle. Press Esc to cancel. The capture goes through the backend's OCR and local
  vision services like an upload in the app.
- **Pasted text**: the side panel also has a text box with a **Check text** button.

The toolbar button opens the side panel. The panel shows the backend's health, the running
check with a cancel button, and then the claims, origin, persuasion and image description.
One check runs at a time; starting another cancels the current one.

## Settings

The panel's gear icon lets you change the backend URL. The default is `http://127.0.0.1:8000`.
A different host asks for permission to contact it the first time, since the manifest only
pre-authorises localhost. The backend has no authentication, so point it only at a server you
control.

## Checks

```bash
npm run check   # type-check
npm test        # pure helpers (crop and thumbnail geometry)
npm run build
```

## Layout

- `manifest.json`: Manifest V3, context menus, side panel, `activeTab` plus `scripting` for
  on-demand capture, host permission for localhost only.
- `src/background.ts`: service worker. Creates the menus, captures or fetches the image, calls
  `/check`, and stores the job in `chrome.storage.session` so the panel can follow it.
- `src/content.ts`: the drag-to-select overlay, injected only when the region menu item is used.
- `src/sidepanel.tsx`: the panel UI. Types, verdict labels and persuasion copy are imported from
  `frontend/src/check.ts` so the two clients stay in step.
- `build.mjs`: esbuild bundling into `dist/`.

## Limits

- Chrome only. Firefox uses a different sidebar API.
- The backend returns one response when the whole check is done, so the panel shows an elapsed
  timer rather than per-stage progress.
- Capture needs the image or region to be visible in the tab; the extension does not scroll
  through or stitch long pages.
- Pages where Chrome blocks extensions (the Web Store, `chrome://` pages, some PDFs) cannot be
  captured, but pasted text still works.
