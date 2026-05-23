# MIDI Chord Analyzer

DTM向けに、MIDIファイルから小節単位のコード候補を推定するMVPです。

## Stack

- React + TypeScript + Vite
- Python backend, standard library only
- MIDI parser and chord analyzer in `backend/`

## Run

Backend:

```cmd
scripts\start_backend.cmd
```

Frontend:

```cmd
scripts\start_frontend.cmd
```

Open:

```text
http://127.0.0.1:5174
```

Demo MIDI:

```text
samples/pop_progression.mid
```

## Test

```powershell
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s backend/tests
```

## MVP Scope

- Upload `.mid` / `.midi`
- Parse Standard MIDI File tracks, tempo, time signature, and note events
- Exclude drum channel 10 from harmonic analysis
- Estimate key from pitch class distribution
- Estimate one chord per bar with alternatives and confidence
- Show chord progression, bar timeline, track list, and a compact piano roll

## Next Useful Additions

- Beat-level or half-bar chord segmentation
- User correction and saved analysis projects
- Roman numeral analysis
- MusicXML / MIDI chord track export
- FastAPI replacement once external Python dependencies are available
