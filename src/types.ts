export type PitchClassWeight = {
  pc: number;
  name: string;
  weight: number;
};

export type ChordAlternative = {
  chord: string;
  root: string | null;
  rootPc: number | null;
  quality: string;
  bass: string | null;
  bassPc: number | null;
  confidence: number;
};

export type ChordSegment = ChordAlternative & {
  index: number;
  bar: number;
  startTick: number;
  endTick: number;
  startSeconds: number;
  endSeconds: number;
  alternatives: ChordAlternative[];
  pitchClasses: PitchClassWeight[];
};

export type MidiNote = {
  track: number;
  channel: number;
  pitch: number;
  name: string;
  velocity: number;
  startTick: number;
  endTick: number;
  startSeconds: number;
  endSeconds: number;
};

export type TrackInfo = {
  index: number;
  name: string;
  noteCount: number;
  channels: number[];
};

export type AnalysisResult = {
  fileName: string;
  format: number;
  ticksPerBeat: number;
  durationTicks: number;
  durationSeconds: number;
  tempoBpm: number;
  timeSignature: {
    numerator: number;
    denominator: number;
  };
  keyEstimate: {
    name: string;
    tonic: string;
    tonicPc: number;
    mode: "major" | "minor";
    confidence: number;
  };
  tracks: TrackInfo[];
  chords: ChordSegment[];
  progression: string[];
  notes: MidiNote[];
};
