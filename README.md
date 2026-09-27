# Live Translator

> **Real-time multilingual live subtitle system**  
> Sinhala · Tamil · English — built for live physical events, runs entirely on localhost.

---

## System Overview

```
Audio mixer → USB sound card → Laptop
                                  │
                         ┌────────┴─────────┐
                         │  Python Backend  │   ws://127.0.0.1:8000
                         │  (FastAPI)       │◄──────────────────────┐
                         │                  │                       │
                         │  Google STT ─────┤                       │
                         │  Google Translate │                       │
                         └──────────────────┘                       │
                                                                    │
                         ┌──────────────────┐   WebSocket           │
                         │ React Frontend   │───────────────────────┘
                         │ (Vite, port 5173)│
                         │                  │
                         │ • Slide viewer   │
                         │ • Subtitles      │
                         │ • Device select  │
                         └──────────────────┘
```

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11+ |
| Node.js | 18+ |
| npm | 9+ |
| Google Cloud project | with Speech-to-Text & Translation APIs enabled |

---

## Step 1 — Google Cloud Setup

### 1a. Enable APIs
In the [Google Cloud Console](https://console.cloud.google.com):
1. Go to **APIs & Services → Library**
2. Enable **Cloud Speech-to-Text API**
3. Enable **Cloud Translation API**

### 1b. Create a Service Account
1. Go to **IAM & Admin → Service Accounts**
2. Create a new service account (e.g. `live-translator-sa`)
3. Grant it these roles:
   - **Cloud Speech Client**
   - **Cloud Translation API User**
4. Create a JSON key → download it

### 1c. Place the key file
```
Live Translator/
└── backend/
    └── keys/
        └── service_account.json    ← put your downloaded JSON key here
```

> **⚠ Security**: `keys/` is in `.gitignore`. Never commit your service account key.

---

## Step 2 — Backend Setup

```powershell
# From the project root
cd backend

# Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Configure environment
Copy-Item .env.example .env
# Edit .env: confirm GOOGLE_APPLICATION_CREDENTIALS path and GOOGLE_CLOUD_PROJECT
notepad .env
```

### Required `.env` fields:
```env
GOOGLE_APPLICATION_CREDENTIALS=./keys/service_account.json
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
```

---

## Step 3 — Frontend Setup

```powershell
# From the project root
cd frontend

# Install Node dependencies
npm install

# Configure environment (defaults work for localhost)
Copy-Item .env.example .env
```

---

## Step 4 — Running for the Live Event

Open **two terminal windows**:

### Terminal 1 — Backend
```powershell
cd backend
.\venv\Scripts\Activate.ps1
uvicorn main:app --host 127.0.0.1 --port 8000
```

Expected output:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

### Terminal 2 — Frontend
```powershell
cd frontend
npm run dev
```

Expected output:
```
  VITE v5.x.x  ready in xxx ms
  ➜  Local:   http://127.0.0.1:5173/
```

Open **http://127.0.0.1:5173** in Chrome or Edge.

---

## Step 5 — Event Day Checklist

- [ ] Backend is running (green dot in the top status bar)
- [ ] USB sound card is connected and appears in the device dropdown
- [ ] The **USB** badge shows next to the sound card in the dropdown
- [ ] The **active device** status banner confirms the correct device is selected
- [ ] Load the presentation PDF using the drag-and-drop zone
- [ ] Do a 30-second test with a speaker — check VU meter is responding and subtitles appear
- [ ] Click **Start Translation** — confirm the green recording dot pulses

---

## Presentation Files

The slide viewer renders **PDF files** directly.  

For **.pptx** files: export as PDF from PowerPoint first:
> **File → Export → Create PDF/XPS Document**

This is standard practice for all presentation display systems and ensures
pixel-perfect slide rendering during the event.

---

## Audio Configuration Notes

| Setting | Value | Reason |
|---|---|---|
| Sample rate | 16 000 Hz | Google STT's optimal rate |
| Channels | Mono (1) | Reduces data; STT is mono |
| Bit depth | 16-bit int (LINEAR16) | Native STT format |
| Chunk size | ~256 ms | Streaming latency balance |
| Echo cancellation | Off | Handled by backend (noisereduce) |
| Noise suppression | Off | Handled by backend |

**Tuning noise reduction**: edit `NOISE_REDUCTION_STRENGTH` in `backend/.env`.
- `0.0` = off (use if speech sounds artefacted)
- `0.5` = default (good for venue HVAC/hum)
- `1.0` = aggressive (use in very noisy environments)

---

## Project Structure

```
Live Translator/
├── .gitignore
├── README.md
│
├── backend/
│   ├── main.py               ← FastAPI app entry point
│   ├── websocket_handler.py  ← WebSocket session lifecycle
│   ├── stt_client.py         ← Google STT streaming + auto-restart
│   ├── translation_client.py ← Google Translate (concurrent)
│   ├── audio_processor.py    ← noisereduce preprocessing
│   ├── requirements.txt
│   ├── .env.example
│   └── keys/                 ← Place service_account.json here
│
└── frontend/
    ├── index.html
    ├── package.json
    ├── vite.config.js
    ├── tailwind.config.js
    ├── postcss.config.js
    ├── .env.example
    └── src/
        ├── main.jsx
        ├── App.jsx
        ├── index.css
        ├── hooks/
        │   ├── useWebSocket.js        ← WS connection + reconnect
        │   ├── useAudioStream.js      ← getUserMedia + PCM streaming
        │   └── useDeviceEnumerator.js ← USB device auto-detection
        └── components/
            ├── StatusBar.jsx          ← Backend health + clock
            ├── PowerPointViewer.jsx   ← 16:9 PDF slide viewer
            ├── SubtitlePanel.jsx      ← 3-line subtitle display
            ├── TranslationControls.jsx← Start/Stop + VU meter
            └── DeviceSelector.jsx     ← Audio device dropdown
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Backend offline" in status bar | Start the backend server; check port 8000 is free |
| No devices in dropdown | Click Refresh; allow microphone permission in browser |
| VU meter not moving | Wrong input device selected; choose the USB sound card |
| Subtitles not appearing | Check Google Cloud credentials; check backend terminal for errors |
| STT says "UNAUTHENTICATED" | Confirm `GOOGLE_APPLICATION_CREDENTIALS` path in `.env` |
| Audio sounds distorted | Lower `NOISE_REDUCTION_STRENGTH` to 0.2–0.3 |
| Stream cuts every 5 min | Expected — the backend auto-restarts the STT session seamlessly |

---

## Language Support

| Language | STT Code | Translate Code |
|---|---|---|
| Sinhala | `si-LK` | `si` |
| Tamil | `ta-LK` (primary) / `ta-IN` | `ta` |
| English | `en-US` | `en` |

Mixed-language speech (e.g. Tamil sentence with English technical terms) is
handled automatically by Google STT's `alternativeLanguageCodes` feature.
No manual language switching is required by the operator.
