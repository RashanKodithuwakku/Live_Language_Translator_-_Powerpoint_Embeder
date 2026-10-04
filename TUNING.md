# TUNING.md — Live Translator (accuracy, latency, budget)

## What changed (short diagnosis → fix)

| Problem | Cause in previous code | Fix now |
|--------|------------------------|---------|
| High latency | Finals-only captions; spectral denoise ~15–30 ms/chunk; Google si/ta slow endpointing | Interim original line; denoise **OFF**; local silence rotation; EVENT progressive translate |
| Bad mixed language | `alternativeLanguageCodes` picks one language per utterance and favours primary | EVENT: parallel si / ta / en streams + confidence×script arbiter. ECO: single scout (cheap) |
| Credit burn | Streams open for silence; denoise on; no budget | VAD gate + pre-roll; idle close 12 s; auto-pause 180 s; usage ledger; ECO hard-stop |
| UI lag | Level meter re-rendered PowerPoint/pdf.js ~10 Hz | `React.memo` on viewer; rAF-batched subtitle paints |

## Profiles

| | **ECO** (default, daily tests) | **EVENT** (rehearsal + 5–6 Oct) |
|--|-------------------------------|--------------------------------|
| STT | 1 scout stream + alternatives | 3 parallel streams, no alternatives |
| Translate | Finals only | Progressive + authoritative final |
| Budget | Warn 70/90%, **hard stop** at 100% | Warn only — captions never blank |
| Cost | Lowest | ~3× STT while speaking (still VAD-gated) |

Switch in the UI (**Profile** dropdown) or `PROFILE=eco|event` in `backend/.env`.

## Capture modes

- **Mixer / line** (production): browser EC/NS/AGC **off**, prefer 48 kHz, worklet AA-downsample to 16 kHz LINEAR16.
- **Laptop mic** (desk tests): EC/NS/AGC **on**.

## Budget (do not drain the free trial)

Suggested defaults in `.env`:

```
DAILY_BUDGET_USD=10
TOTAL_BUDGET_USD=250
PROFILE=eco
NOISE_REDUCTION_STRENGTH=0
VAD_ENABLED=true
MODE=live
```

- Watch the small **$ / %** badge under Start/Stop.
- Edit rates in `backend/pricing.json` to match your Google bill.
- Ledger: `backend/usage_ledger.json` (git-ignored).
- ECO stop → send `OVERRIDE` over the socket or `POST /api/budget/override` for a 4 h bypass.
- `MODE=cache` avoids Google entirely (UI only; not for accuracy).

**Do not leave EVENT profile running for hours of silent desk testing** — three streams bill while speech is detected.

## Phrase hints

Edit `backend/phrases.json` (names, titles, venue terms). Applied to every recogniser. Free accuracy win.

## Content filter (captions)

Every caption line — original, Sinhala, Tamil, live previews and finals — passes through `backend/content_filter.py`. The original is checked **before** translation, and both translations **after** it (translation can create an offensive word from innocent speech).

- `FILTER_ACTION=drop` (event days): a caption containing a blocked word is not shown at all.
- `FILTER_ACTION=mask` (testing): each blocked word shows as `…`, so you can see what is caught.
- `STT_PROFANITY_FILTER=true`: Google's own masking (mainly English); its `f***` output is also blocked.
- Word list: `backend/blocklist.json`, grouped by language. `exact` = whole word only (use for short words that start innocent words, e.g. පක vs පක්ෂය); `prefix` = stem, catches every suffixed form (ලිංගික → ලිංගිකත්වය); `contains` = anywhere in a word, catches compounds (ලිංග → සමලිංගික, ලිංගය, ලිංගභේදය); `phrases` = multi-word. Edits apply within ~5 s, no restart.
- Extra protection (Sinhala-first): recogniser letter confusions are treated as the same letter (ණ/න, ළ/ල, ෂ/ශ, ථ/ත, ධ/ද, ඟ/ංග, long/short vowel signs; Tamil ண/ந/ன, ற/ர, ள/ழ/ல); invisible joiners are ignored; a word split in two ("හුත් තා") is rejoined; in live previews an unfinished last word that could become a blocked word ("ලිංගි…", "homose…") is held back; once a sentence's preview contained a blocked word, the rest of that sentence's previews stay hidden.
- After editing the list run `python tests/test_content_filter.py` (from `backend/`, venv active). It checks 100+ offensive forms are blocked and that event vocabulary (all of `phrases.json`) and everyday words (පක්ෂය, කාමරය, ශුක්‍රවාදා, ගණිතය, சூத்திரம், பண்ணி…) still pass. The backend also logs a warning at startup if any `phrases.json` entry would be blocked.
- The backend log records only counts ("1 word(s) dropped …"), never the words.
- Operator **Clear** button (bottom-right of the subtitle area) blanks all three lines instantly.

## Mixer calibration checklist

1. Profile **EVENT**, capture **Mixer / line**, USB sound card selected (green line).
2. Peaks about **−12…−6 dBFS**; never sit at CLIP.
3. Speak 30 s Sinhala, Tamil, English (and mixed). Confirm original line shows the right script.
4. Click **Latency** — aim for interim original ≲ 1.5 s when the venue link is healthy.
5. Confirm `/health` → `credentials_found: true` and budget % comfortable.
6. Full-screen (F11), sleep disabled.

## Important `.env` flags

See `backend/.env.example`. Highlights: `ARBITER_STRATEGY`, `PARALLEL_LANGUAGES`, `VAD_*`, `IDLE_*`, `TRANSLATE_*`, `ENABLE_STRATEGY_2` (off).

## Pinned deps

Backend: `requirements.txt` (incl. `webrtcvad==2.0.10`). Frontend: `package.json` / lockfile. Do not float majors before the event.

## What still needs a live check (not done here to save credit)

- End-to-end p50/p95 with the real mixer (this upgrade was verified with offline unit checks + build only).
- WER table ECO vs EVENT / Strategy 0 vs 1 on your WAV set (`scripts/eval_wer.py` can be added when you have labelled audio).
- asia-southeast1 regional Speech endpoint (v1 client default; changing region needs client options — left as default global until benchmarked).
