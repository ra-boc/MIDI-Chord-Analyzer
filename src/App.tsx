import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import type { AnalysisResult, ChordSegment, MidiNote } from "./types";

const API_ENDPOINT = "/api/analyze";
const MAX_SCHEDULED_NOTES = 4200;
const PIANO_INSTRUMENT = "acoustic_grand_piano";
const PIANO_SOUNDFONT_URL = "/soundfonts/acoustic_grand_piano-mp3.js";
const SOUNDFONT_NOTE_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"];
const NOTE_NAME_TO_PITCH_CLASS: Record<string, number> = {
  C: 0,
  "C#": 1,
  Db: 1,
  D: 2,
  "D#": 3,
  Eb: 3,
  E: 4,
  F: 5,
  "F#": 6,
  Gb: 6,
  G: 7,
  "G#": 8,
  Ab: 8,
  A: 9,
  "A#": 10,
  Bb: 10,
  B: 11,
};

type WebAudioWindow = Window &
  typeof globalThis & {
    webkitAudioContext?: typeof AudioContext;
    MIDI?: {
      Soundfont?: Record<string, SoundfontMap>;
    };
  };

type SoundfontMap = Record<string, string>;

type DecodedPianoSample = {
  buffer: AudioBuffer;
  sourcePitch: number;
};

let pianoSoundfontPromise: Promise<SoundfontMap> | null = null;

function App() {
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const analyzeFile = async (file: File) => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(API_ENDPOINT, {
        method: "POST",
        headers: {
          "Content-Type": "application/octet-stream",
          "X-File-Name": encodeURIComponent(file.name),
        },
        body: file,
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error ?? "解析に失敗しました。");
      }
      setResult(payload as AnalysisResult);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "解析に失敗しました。");
    } finally {
      setLoading(false);
    }
  };

  const onInputChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      void analyzeFile(file);
    }
  };

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) {
      void analyzeFile(file);
    }
  };

  return (
    <main className="appShell">
      <header className="topBar">
        <div>
          <p className="eyebrow">DTM MIDI tool</p>
          <h1>MIDI Chord Analyzer</h1>
        </div>
        <button className="ghostButton" type="button" onClick={() => inputRef.current?.click()}>
          MIDIを選択
        </button>
      </header>

      <section className="uploadBand">
        <label
          className={`dropZone ${dragging ? "isDragging" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <input ref={inputRef} type="file" accept=".mid,.midi,audio/midi" onChange={onInputChange} />
          <span className="dropIcon">MID</span>
          <span className="dropTitle">MIDIファイルを解析</span>
          <span className="dropMeta">.mid / .midi</span>
        </label>
        {loading && <p className="statusText">解析しています...</p>}
        {error && <p className="errorText">{error}</p>}
      </section>

      {result ? <AnalysisView result={result} /> : <EmptyState />}
    </main>
  );
}

function EmptyState() {
  return (
    <section className="emptyGrid">
      <div className="emptyPanel">
        <span className="panelKicker">MVP</span>
        <h2>コード進行、キー、ピアノロールを表示します</h2>
      </div>
      <div className="emptyPanel tonePanel">
        <span className="panelKicker">Engine</span>
        <h2>ドラムチャンネルを除外して小節単位で推定します</h2>
      </div>
    </section>
  );
}

function AnalysisView({ result }: { result: AnalysisResult }) {
  return (
    <div className="analysisStack">
      <Summary result={result} />
      <AudioPlayer result={result} />
      <Progression result={result} />
      <ChordTimeline chords={result.chords} />
      <PianoRoll notes={result.notes} chords={result.chords} durationTicks={result.durationTicks} />
      <TrackTable result={result} />
    </div>
  );
}

function AudioPlayer({ result }: { result: AnalysisResult }) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [volume, setVolume] = useState(0.36);
  const [playerMessage, setPlayerMessage] = useState("Piano SoundFont ready");
  const [playerError, setPlayerError] = useState<string | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const activeNodesRef = useRef<Array<AudioScheduledSourceNode | GainNode>>([]);
  const animationFrameRef = useRef<number | null>(null);
  const masterGainRef = useRef<GainNode | null>(null);
  const sampleCacheRef = useRef<Map<number, DecodedPianoSample>>(new Map());
  const startTimeRef = useRef(0);

  const playableNotes = useMemo(
    () =>
      result.notes
        .filter((note) => note.endSeconds > note.startSeconds)
        .slice(0, MAX_SCHEDULED_NOTES),
    [result.notes],
  );
  const skippedNotes = Math.max(0, result.notes.length - playableNotes.length);

  useEffect(() => {
    return () => {
      stopPlayback();
    };
  }, []);

  useEffect(() => {
    stopPlayback();
    setPosition(0);
  }, [result.fileName]);

  useEffect(() => {
    if (masterGainRef.current && audioContextRef.current) {
      masterGainRef.current.gain.setTargetAtTime(volume, audioContextRef.current.currentTime, 0.01);
    }
  }, [volume]);

  const stopPlayback = () => {
    if (animationFrameRef.current !== null) {
      window.cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    for (const node of activeNodesRef.current) {
      try {
        if ("stop" in node) {
          node.stop(0);
        } else {
          node.disconnect();
        }
      } catch {
        // Already stopped or disconnected.
      }
    }
    activeNodesRef.current = [];
    masterGainRef.current = null;
    setIsPlaying(false);
  };

  const getAudioContext = () => {
    if (audioContextRef.current) {
      return audioContextRef.current;
    }
    const AudioContextClass = window.AudioContext ?? (window as WebAudioWindow).webkitAudioContext;
    if (!AudioContextClass) {
      throw new Error("このブラウザはWeb Audio APIに対応していません。");
    }
    audioContextRef.current = new AudioContextClass();
    return audioContextRef.current;
  };

  const play = async () => {
    stopPlayback();
    setPlayerError(null);
    setPlayerMessage("ピアノSoundFontを読み込み中...");

    try {
      const context = getAudioContext();
      await context.resume();
      const soundfont = await loadPianoSoundfont();
      setPlayerMessage("ピアノサンプルを準備中...");
      await loadRequiredPianoSamples(context, soundfont, playableNotes, sampleCacheRef.current);

      const masterGain = context.createGain();
      masterGain.gain.setValueAtTime(volume, context.currentTime);
      masterGain.connect(context.destination);
      masterGainRef.current = masterGain;
      activeNodesRef.current.push(masterGain);

      const scheduledStart = context.currentTime + 0.06;
      startTimeRef.current = scheduledStart;
      setPosition(0);
      setIsPlaying(true);
      setPlayerMessage("Piano SoundFont playing");

      for (const note of playableNotes) {
        const sample = sampleCacheRef.current.get(note.pitch);
        if (sample) {
          activeNodesRef.current.push(...schedulePianoNote(context, masterGain, note, sample, scheduledStart));
        }
      }

      const updatePosition = () => {
        const elapsed = Math.max(0, context.currentTime - startTimeRef.current);
        setPosition(Math.min(result.durationSeconds, elapsed));
        if (elapsed >= result.durationSeconds + 0.12) {
          stopPlayback();
          setPosition(result.durationSeconds);
          setPlayerMessage("Piano SoundFont ready");
          return;
        }
        animationFrameRef.current = window.requestAnimationFrame(updatePosition);
      };
      animationFrameRef.current = window.requestAnimationFrame(updatePosition);
    } catch (caught) {
      stopPlayback();
      const message = caught instanceof Error ? caught.message : "ピアノSoundFontの読み込みに失敗しました。";
      setPlayerError(message);
      setPlayerMessage("Piano SoundFont unavailable");
    }
  };

  const progress = result.durationSeconds > 0 ? position / result.durationSeconds : 0;

  return (
    <section className="sectionBlock playerBlock">
      <div className="sectionHeader">
        <h2>再生</h2>
        <span>
          {formatTime(position)} / {formatTime(result.durationSeconds)}
        </span>
      </div>
      <div className="playerControls">
        <button className="primaryButton" type="button" onClick={() => void play()} disabled={!playableNotes.length}>
          {isPlaying ? "最初から再生" : "再生"}
        </button>
        <button className="ghostButton compactButton" type="button" onClick={stopPlayback} disabled={!isPlaying}>
          停止
        </button>
        <label className="controlField">
          <span>音量</span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={volume}
            onChange={(event) => setVolume(Number(event.target.value))}
          />
        </label>
        <div className="soundfontBadge">
          <span>音源</span>
          <strong>Acoustic Grand Piano</strong>
        </div>
      </div>
      <div className="playbackRail" aria-label="再生位置">
        <span style={{ width: `${Math.min(100, Math.max(0, progress * 100))}%` }} />
      </div>
      {playerError ? (
        <p className="errorText">{playerError}</p>
      ) : (
        <p className="playerNote">
          {playerMessage}
          {skippedNotes > 0 && ` / ${skippedNotes.toLocaleString()} notes skipped for this MVP.`}
        </p>
      )}
    </section>
  );
}

function Summary({ result }: { result: AnalysisResult }) {
  const duration = `${result.durationSeconds.toFixed(1)}s`;
  const meter = `${result.timeSignature.numerator}/${result.timeSignature.denominator}`;
  const noteCount = result.notes.length.toLocaleString();

  return (
    <section className="summaryGrid">
      <Metric label="File" value={result.fileName} />
      <Metric label="Key" value={result.keyEstimate.name} detail={`${percent(result.keyEstimate.confidence)} confidence`} />
      <Metric label="Tempo" value={`${result.tempoBpm} BPM`} detail={`${meter} / ${duration}`} />
      <Metric label="Notes" value={noteCount} detail={`${result.tracks.length} tracks`} />
    </section>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return (
    <article className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </article>
  );
}

function Progression({ result }: { result: AnalysisResult }) {
  return (
    <section className="sectionBlock">
      <div className="sectionHeader">
        <h2>コード進行</h2>
        <span>{result.progression.length} changes</span>
      </div>
      <div className="progressionLine">
        {result.progression.map((chord, index) => (
          <span key={`${chord}-${index}`}>{chord}</span>
        ))}
      </div>
    </section>
  );
}

function ChordTimeline({ chords }: { chords: ChordSegment[] }) {
  return (
    <section className="sectionBlock">
      <div className="sectionHeader">
        <h2>小節タイムライン</h2>
        <span>{chords.length} bars</span>
      </div>
      <div className="chordGrid">
        {chords.map((segment) => (
          <article key={segment.index} className="chordCard">
            <div className="barNumber">Bar {segment.bar}</div>
            <strong>{segment.chord}</strong>
            <div className="confidence">
              <span style={{ width: `${segment.confidence * 100}%` }} />
            </div>
            <small>{percent(segment.confidence)}</small>
            <div className="pitchClassList">
              {segment.pitchClasses.slice(0, 5).map((pitch) => (
                <span key={pitch.pc}>{pitch.name}</span>
              ))}
            </div>
            {segment.alternatives.length > 0 && (
              <p className="alternatives">
                {segment.alternatives.map((alt) => alt.chord).join(" / ")}
              </p>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function PianoRoll({
  notes,
  chords,
  durationTicks,
}: {
  notes: MidiNote[];
  chords: ChordSegment[];
  durationTicks: number;
}) {
  const geometry = useMemo(() => {
    if (!notes.length) {
      return { minPitch: 48, maxPitch: 72, width: 900, height: 320, rowHeight: 14 };
    }
    const pitches = notes.map((note) => note.pitch);
    const minPitch = Math.max(0, Math.min(...pitches) - 2);
    const maxPitch = Math.min(127, Math.max(...pitches) + 2);
    const rowHeight = 14;
    const width = Math.max(900, chords.length * 150);
    const height = Math.max(280, (maxPitch - minPitch + 1) * rowHeight);
    return { minPitch, maxPitch, width, height, rowHeight };
  }, [chords.length, notes]);

  const safeDuration = Math.max(durationTicks, 1);

  return (
    <section className="sectionBlock">
      <div className="sectionHeader">
        <h2>ピアノロール</h2>
        <span>{notes.length.toLocaleString()} notes</span>
      </div>
      <div className="rollViewport">
        <div className="pianoRoll" style={{ width: geometry.width, height: geometry.height }}>
          {chords.map((chord) => (
            <div
              key={`bar-${chord.index}`}
              className="barLine"
              style={{ left: `${(chord.startTick / safeDuration) * 100}%` }}
            >
              <span>{chord.chord}</span>
            </div>
          ))}
          {notes.map((note, index) => {
            const left = (note.startTick / safeDuration) * geometry.width;
            const width = Math.max(4, ((note.endTick - note.startTick) / safeDuration) * geometry.width);
            const top = (geometry.maxPitch - note.pitch) * geometry.rowHeight;
            return (
              <span
                key={`${note.track}-${note.pitch}-${note.startTick}-${index}`}
                className="noteBlock"
                title={`${note.name} ch.${note.channel}`}
                style={{
                  left,
                  top,
                  width,
                  height: geometry.rowHeight - 3,
                  opacity: 0.55 + note.velocity / 280,
                }}
              />
            );
          })}
        </div>
      </div>
    </section>
  );
}

function TrackTable({ result }: { result: AnalysisResult }) {
  return (
    <section className="sectionBlock">
      <div className="sectionHeader">
        <h2>トラック</h2>
        <span>format {result.format}</span>
      </div>
      <div className="trackTable">
        {result.tracks.map((track) => (
          <div key={track.index} className="trackRow">
            <strong>{track.name}</strong>
            <span>{track.noteCount.toLocaleString()} notes</span>
            <span>ch. {track.channels.join(", ") || "-"}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function schedulePianoNote(
  context: AudioContext,
  output: AudioNode,
  note: MidiNote,
  sample: DecodedPianoSample,
  playbackStart: number,
): [AudioBufferSourceNode, GainNode] {
  const start = playbackStart + note.startSeconds;
  const end = playbackStart + note.endSeconds;
  const duration = Math.max(0.04, end - start);
  const source = context.createBufferSource();
  const gain = context.createGain();
  const noteGain = Math.max(0.01, (note.velocity / 127) * 0.78);
  const attack = Math.min(0.015, duration * 0.2);
  const release = Math.min(0.18, duration * 0.45);

  source.buffer = sample.buffer;
  source.playbackRate.setValueAtTime(2 ** ((note.pitch - sample.sourcePitch) / 12), start);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.linearRampToValueAtTime(noteGain, start + attack);
  gain.gain.setValueAtTime(noteGain * 0.72, Math.max(start + attack, end - release));
  gain.gain.linearRampToValueAtTime(0.0001, end + release);

  source.connect(gain);
  gain.connect(output);
  source.start(start);
  source.stop(end + release + 0.02);
  return [source, gain];
}

function loadPianoSoundfont(): Promise<SoundfontMap> {
  const soundfontWindow = window as WebAudioWindow;
  const loadedSoundfont = soundfontWindow.MIDI?.Soundfont?.[PIANO_INSTRUMENT];
  if (loadedSoundfont) {
    return Promise.resolve(loadedSoundfont);
  }

  if (pianoSoundfontPromise) {
    return pianoSoundfontPromise;
  }

  pianoSoundfontPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = PIANO_SOUNDFONT_URL;
    script.async = true;
    script.onload = () => {
      const soundfont = (window as WebAudioWindow).MIDI?.Soundfont?.[PIANO_INSTRUMENT];
      if (soundfont) {
        resolve(soundfont);
      } else {
        reject(new Error("ピアノSoundFontを読み込めませんでした。"));
      }
    };
    script.onerror = () => reject(new Error("ピアノSoundFontのダウンロードに失敗しました。"));
    document.head.appendChild(script);
  });

  return pianoSoundfontPromise;
}

async function loadRequiredPianoSamples(
  context: AudioContext,
  soundfont: SoundfontMap,
  notes: MidiNote[],
  cache: Map<number, DecodedPianoSample>,
) {
  const uniquePitches = Array.from(new Set(notes.map((note) => note.pitch)));
  await Promise.all(uniquePitches.map((pitch) => loadPianoSample(context, soundfont, pitch, cache)));
}

async function loadPianoSample(
  context: AudioContext,
  soundfont: SoundfontMap,
  pitch: number,
  cache: Map<number, DecodedPianoSample>,
) {
  const cached = cache.get(pitch);
  if (cached) {
    return cached;
  }

  const { dataUrl, sourcePitch } = findPianoSample(soundfont, pitch);
  const response = await fetch(dataUrl);
  const arrayBuffer = await response.arrayBuffer();
  const buffer = await context.decodeAudioData(arrayBuffer.slice(0));
  const sample = { buffer, sourcePitch };
  cache.set(pitch, sample);
  return sample;
}

function findPianoSample(soundfont: SoundfontMap, pitch: number) {
  const exactName = midiToSoundfontName(pitch);
  if (soundfont[exactName]) {
    return { dataUrl: soundfont[exactName], sourcePitch: pitch };
  }

  const candidates = Object.keys(soundfont)
    .map((name) => ({ name, pitch: soundfontNameToMidi(name) }))
    .filter((candidate): candidate is { name: string; pitch: number } => candidate.pitch !== null);
  if (!candidates.length) {
    throw new Error("ピアノSoundFontに使用できるサンプルがありません。");
  }
  const closest = candidates.reduce((best, candidate) =>
    Math.abs(candidate.pitch - pitch) < Math.abs(best.pitch - pitch) ? candidate : best,
  );
  return { dataUrl: soundfont[closest.name], sourcePitch: closest.pitch };
}

function midiToSoundfontName(pitch: number) {
  const octave = Math.floor(pitch / 12) - 1;
  return `${SOUNDFONT_NOTE_NAMES[pitch % 12]}${octave}`;
}

function soundfontNameToMidi(name: string) {
  const match = /^([A-G](?:b|#)?)(-?\d+)$/.exec(name);
  if (!match) {
    return null;
  }
  const pitchClass = NOTE_NAME_TO_PITCH_CLASS[match[1]];
  if (pitchClass === undefined) {
    return null;
  }
  return (Number(match[2]) + 1) * 12 + pitchClass;
}

function formatTime(seconds: number) {
  const safeSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safeSeconds / 60);
  const remainder = String(safeSeconds % 60).padStart(2, "0");
  return `${minutes}:${remainder}`;
}

export default App;
