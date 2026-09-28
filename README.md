# Live Translator

Real-time multilingual subtitles for live events: Sinhala · Tamil · English
(mixed mid-sentence), shown under the event's PowerPoint slides. Runs
entirely on one event laptop (localhost); only Google Cloud Speech-to-Text
and Translation are reached over the internet.

```
Event mics → Mixer → (aux / record out) → USB sound card → Laptop USB
                                                     │
                     ┌───────────────────────────────┴──────────────┐
                     │ Browser (React, http://127.0.0.1:5173)       │
                     │  getUserMedia(USB card) → AudioWorklet       │
                     │  100 ms LINEAR16 chunks ── WebSocket ──┐     │
                     │  Slides (pdf.js) + slide videos        │     │
                     └────────────────────────────────────────┼─────┘
                                                              ▼
                     ┌──────────────────────────────────────────────┐
                     │ Python backend (FastAPI, 127.0.0.1:8000)     │
                     │  80 Hz high-pass + spectral gate             │
                     │  Google STT streaming (si-LK + ta-LK, en-US) │
                     │  final sentence → Translate ×2 in parallel   │
                     │  .pptx → PDF via PowerPoint + video extract  │
                     └──────────────────────────────────────────────┘
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Windows 10/11 laptop | macOS/Linux work too, using LibreOffice for .pptx |
| Python 3.11+ | tested with 3.13 |
| Node.js 20.19+ or 22.12+ | required by Vite 7 |
| Google Chrome or Microsoft Edge | AudioWorklet + `setSinkId` for slide audio routing |
| Microsoft PowerPoint **or** LibreOffice | converts .pptx slides (PowerPoint gives pixel-identical output) |
| Google Cloud project | Speech-to-Text + Translation APIs enabled |

---

## 1. Google Cloud service account key

1. In the [Google Cloud Console](https://console.cloud.google.com), open
   **APIs & Services → Library** and enable **Cloud Speech-to-Text API** and
   **Cloud Translation API**.
2. **IAM & Admin → Service Accounts → Create service account**
   (e.g. `live-translator`). Grant the roles **Cloud Speech Client** and
   **Cloud Translation API User**.
3. Open the account → **Keys → Add key → Create new key → JSON**. A `.json`
   file downloads.
4. Put the downloaded `.json` key in `backend/` and point `backend/.env` at it
   (copy `.env.example` to `.env` first). Never commit the key or `.env`:

```
Live Translator/
└── backend/
    ├── .env                       GOOGLE_APPLICATION_CREDENTIALS=./your-service-account.json
    └── your-service-account.json  ← your Google key (git-ignored)
```

The key is read only by the backend (via `GOOGLE_APPLICATION_CREDENTIALS`
in `backend/.env`) and never sent to the browser. `keys/`, `*.json` and
`.env` are git-ignored — never commit the key. The operator panel shows
**Key missing** in amber if the backend can't find it.

---

## 2. Install

### Backend

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # defaults work; edit if the key lives elsewhere
```

### Frontend

```powershell
cd frontend
npm install
Copy-Item .env.example .env      # defaults work for localhost
```

---

## 3. Run for the event

Two terminals:

**Terminal 1 — backend**
```powershell
cd backend
.\venv\Scripts\Activate.ps1
uvicorn main:app --host 127.0.0.1 --port 8000
```

**Terminal 2 — frontend**
```powershell
cd frontend
npm run dev
```

Open **http://127.0.0.1:5173** in Chrome/Edge, allow microphone access when
asked, and press **F11** for full screen.

For the most robust event setup you can serve a production build instead
of the dev server: `npm run build` then `npm run preview` (opens on
http://127.0.0.1:4173).

---

## 4. Using it

**Slides (top box)**
- Drag a `.pptx` or `.pdf` into the box, or click **Choose from device**.
- `.pptx` is converted by the backend using PowerPoint (a few seconds; the
  first conversion after boot can take longer while PowerPoint starts).
  Hidden slides are skipped, exactly like PowerPoint's slideshow.
- Change slides with the ◀ ▶ buttons, the arrow keys, or a presentation
  clicker (PageUp/PageDown).
- **Remove** (top-right of the box) unloads the deck so you can load another.
- The loaded `.pptx` survives a browser refresh.

**Videos and sounds in slides**
- Embedded videos play in place, exactly where they sit on the slide, with
  their PowerPoint settings: *Start Automatically* vs *On Click*, *Loop*,
  volume, *Play Full Screen*. Embedded sounds get a click-to-play button
  over their icon.
- Use MP4 (H.264/AAC) inside the deck. WMV/AVI can't play in a browser —
  PowerPoint's *File → Info → Optimize Media Compatibility* converts them.
  Linked (not embedded) and online videos are flagged on the slide.

**Translation (bottom box)**
- **Speaker: Sinhala / Tamil / English** — pick the speaker's *main*
  language before pressing Start. The other two are still recognized when
  mixed in, but Google weighs the first language heavily: English speech
  with *Speaker: Sinhala* comes out as nonsense. Change it (Stop → pick →
  Start) when a speaker of another language takes the stage.
- The **audio input** dropdown auto-selects the USB sound card; the line
  under it turns green (“USB sound card active”) or amber if the selected
  device doesn't look like USB. Verify it before starting.
- **Start** opens the connection and begins capture; **Stop** ends both.
- The input meter should sit mostly in green while people talk; **CLIP**
  means the mixer send is too hot — turn it down at the mixer.
- Subtitles show only the current sentence: Sinhala, Tamil, and the
  original words as spoken. Each new sentence replaces all three lines.

### Keeping slide-video audio out of the translation

Two layers of protection, so a video's soundtrack is never transcribed:

1. **At the mixer (recommended).** Feed the USB sound card from an
   **aux/record send that contains only the speech microphones**, and keep
   the laptop's playback channel turned down on that send. The laptop's
   audio can still go to the PA through the main mix.
2. **In the app (automatic backup).** While any slide video/sound is
   playing audibly, the app sends digital silence instead of the mixer
   feed, and the status reads *Paused — slide media*. Captions resume the
   moment the video pauses or ends. Toggle this under
   **Slide video audio → Pause captions while slide media plays**.

Under **Slide video audio** you can also choose which **output device**
plays slide videos (e.g. the HDMI/PA feed) independently of the system
default.

---

## Event-day checklist

- [ ] Backend terminal shows `Application startup complete`; the panel shows a green **Server** dot (not *Key missing* / *Server offline*)
- [ ] USB sound card plugged in; dropdown shows it with the green “USB sound card active” line
- [ ] Presentation loaded; step through any video slides once to check they play and the sound goes to the right output
- [ ] 30-second sound check: meter moving, no **CLIP**, subtitles appearing
- [ ] Browser in full screen (F11), laptop power saving/sleep disabled

---

## Configuration (`backend/.env`)

| Variable | Default | Purpose |
|---|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | `./your-service-account.json` | Service account key path (relative to `backend/`; never commit the key) |
| `STT_MODEL` | `default` | Keep `default`: `si-LK`/`ta-LK` aren't served by `latest_long` in the v1 API |
| `STT_PRIMARY_LANGUAGE` | `si-LK` | Fallback speaker language (the UI's *Speaker* dropdown overrides it) |
| `STT_ALTERNATIVE_LANGUAGES` | `ta-LK,en-US` | Auto-detected alternatives (use `ta-IN` for Indian Tamil speakers) |
| `STT_SESSION_RESTART_INTERVAL` | `240` | Seconds before the Google stream is rotated (see below) |
| `STT_ENDPOINT_SILENCE_MS` | `700` | Pause that ends a sentence and shows its subtitle |
| `STT_MAX_UTTERANCE_S` | `15` | A non-stop speaker is captioned at the next breath after this |
| `NOISE_REDUCTION_STRENGTH` | `0.5` | Spectral gate 0–1 (0 = off). The 80 Hz high-pass always runs |
| `MAX_PRESENTATION_MB` | `1024` | Upload size limit for .pptx files |
| `LIBREOFFICE_PATH` | auto | Only if LibreOffice is installed somewhere unusual |

---

## How the hard parts work

- **Fast subtitles.** Google's Sinhala/Tamil models take 14–29 s to decide
  a sentence has ended. The backend runs its own voice-activity detector on
  the cleaned audio: after the speaker pauses for 0.7 s it closes that
  sentence's stream (Google then returns the final text within ~0.5 s)
  while a fresh stream is already taking the next words.
- **Google's ~5-minute stream limit.** At the first pause after 4 minutes
  (hard limit 4 min 40 s) the backend opens a new recognition stream and
  routes audio to it, then half-closes the old one so it still delivers the
  words in flight. Streams overlap, so no audio is dropped and the operator
  does nothing. A dropped stream (network blip) is reopened automatically.
- **Reconnects.** If the browser loses the backend (restart, Wi-Fi blip),
  it reconnects on its own with back-off, and the backend starts a fresh
  Google session on connect — no need to press Start again. If the USB
  sound card is unplugged, capture resumes by itself when it's plugged back.
- **Noise cleanup.** 4th-order 80 Hz high-pass (rumble, handling noise),
  then a stationary spectral gate whose noise profile is learned from the
  quietest moments of the last 8 s (HVAC, projector fans), not from the
  speech itself.
- **Translations.** Each final sentence is translated to Sinhala and Tamil
  concurrently; a language that is already the source is passed through
  untouched.

---

## Project structure

```
Live Translator/
├── README.md
├── backend/
│   ├── main.py                  FastAPI app: health, presentation API, WebSocket route
│   ├── websocket_handler.py     Session lifecycle: audio in → captions out
│   ├── stt_client.py            Google STT streaming, threads, seamless rotation
│   ├── translation_client.py    Concurrent Sinhala/Tamil translation
│   ├── audio_processor.py       High-pass + spectral gate
│   ├── presentation_service.py  .pptx → PDF (PowerPoint/LibreOffice) + media extraction
│   ├── requirements.txt
│   ├── .env.example
│   ├── .env                     Settings + key path (git-ignored)
│   └── your-service-account.json  Google key (git-ignored; never push)
└── frontend/
    ├── index.html, package.json, vite.config.js, tailwind.config.js, postcss.config.js
    ├── public/worklets/pcm-capture-processor.js   AudioWorklet (real-time thread)
    └── src/
        ├── App.jsx                      Two-box layout, session wiring
        ├── index.css
        ├── lib/presentationApi.js       Upload / restore / delete decks
        ├── hooks/
        │   ├── useAudioStream.js        USB capture, silence gate, auto-recovery
        │   ├── useWebSocket.js          Connection + auto-reconnect
        │   ├── useDeviceEnumerator.js   Input/output lists, USB auto-select
        │   ├── useBackendHealth.js      Server / key status
        │   └── useElementSize.js        16:9 fitting
        └── components/
            ├── PowerPointViewer.jsx     16:9 stage, navigation, Remove
            ├── presentation/DropZone.jsx
            ├── presentation/SlideMediaLayer.jsx   In-place slide video/audio
            ├── SubtitlePanel.jsx        Three auto-sized lines
            ├── TranslationControls.jsx  Start/Stop, status, input meter
            └── DeviceSelector.jsx       Compact input + slide-audio settings
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| **Server offline** | Start the backend; make sure nothing else uses port 8000 |
| **Key missing** | Put the key `.json` in `backend/` and check `GOOGLE_APPLICATION_CREDENTIALS` in `backend/.env`, then restart the backend |
| “PERMISSION_DENIED” / “API has not been used in project” | Enable Cloud Speech-to-Text API and Cloud Translation API for the project, and check billing is on |
| Subtitles are nonsense | The *Speaker* language doesn't match who is talking |
| Sentences split in the middle | Speaker pauses mid-sentence; raise `STT_ENDPOINT_SILENCE_MS` to 900–1200 |
| “Microphone access is blocked” | Lock icon in the address bar → Microphone → Allow, then **Retry** |
| USB card not in the list | Replug it, then click ↻ next to the dropdown |
| Meter shows **CLIP** | Lower the mixer's send to the USB card |
| Meter flat | Wrong input selected, or the mixer send is muted |
| “.pptx cannot be converted” | Install PowerPoint or LibreOffice, or export the deck to PDF and load that |
| A slide video shows a ⚠ badge | Re-insert it as an embedded MP4 in PowerPoint |
| Captions stuck on *Paused — slide media* | A slide video/sound is still playing — pause it |
| Speech sounds “watery” to recognition | Lower `NOISE_REDUCTION_STRENGTH` (0.2–0.3, or 0) |
