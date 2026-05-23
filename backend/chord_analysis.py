from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .midi_parser import MidiFileData, MidiNote, tick_to_seconds


NOTE_NAMES_SHARP = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
NOTE_NAMES_FLAT = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
FLAT_KEY_TONICS = {1, 3, 5, 6, 8, 10}

MAJOR_PROFILE = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
MINOR_PROFILE = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)


@dataclass(frozen=True)
class ChordTemplate:
    quality: str
    suffix: str
    intervals: tuple[int, ...]


CHORD_TEMPLATES = (
    ChordTemplate("maj7", "maj7", (0, 4, 7, 11)),
    ChordTemplate("dom7", "7", (0, 4, 7, 10)),
    ChordTemplate("six", "6", (0, 4, 7, 9)),
    ChordTemplate("add9", "add9", (0, 2, 4, 7)),
    ChordTemplate("major", "", (0, 4, 7)),
    ChordTemplate("min7", "m7", (0, 3, 7, 10)),
    ChordTemplate("min6", "m6", (0, 3, 7, 9)),
    ChordTemplate("minmaj7", "mMaj7", (0, 3, 7, 11)),
    ChordTemplate("minor", "m", (0, 3, 7)),
    ChordTemplate("halfdim7", "m7b5", (0, 3, 6, 10)),
    ChordTemplate("dim7", "dim7", (0, 3, 6, 9)),
    ChordTemplate("diminished", "dim", (0, 3, 6)),
    ChordTemplate("augmented", "aug", (0, 4, 8)),
    ChordTemplate("sus4", "sus4", (0, 5, 7)),
    ChordTemplate("sus2", "sus2", (0, 2, 7)),
    ChordTemplate("power", "5", (0, 7)),
)


def analyze_midi(midi: MidiFileData, file_name: str = "upload.mid") -> dict[str, Any]:
    harmonic_notes = [note for note in midi.notes if note.channel != 9 and note.duration_ticks > 0]
    all_weights = _pitch_class_weights(harmonic_notes, 0, midi.duration_ticks)
    key_estimate = _estimate_key(all_weights)
    prefer_flats = key_estimate["tonicPc"] in FLAT_KEY_TONICS

    signature = midi.time_signatures[0]
    ticks_per_bar = int(midi.ticks_per_beat * signature.numerator * 4 / signature.denominator)
    if ticks_per_bar <= 0:
        ticks_per_bar = midi.ticks_per_beat * 4

    bar_count = max(1, math.ceil(midi.duration_ticks / ticks_per_bar)) if midi.duration_ticks else 1
    chords = []
    for bar_index in range(bar_count):
        start_tick = bar_index * ticks_per_bar
        end_tick = min((bar_index + 1) * ticks_per_bar, max(midi.duration_ticks, ticks_per_bar))
        weights = _pitch_class_weights(harmonic_notes, start_tick, end_tick)
        segment_notes = _notes_overlapping(harmonic_notes, start_tick, end_tick)
        bass_pc = _bass_pitch_class(segment_notes, start_tick, end_tick)
        candidates = _rank_chords(weights, bass_pc, prefer_flats)

        best = candidates[0] if candidates else _no_chord(start_tick, end_tick)
        chords.append(
            {
                "index": bar_index,
                "bar": bar_index + 1,
                "startTick": start_tick,
                "endTick": end_tick,
                "startSeconds": round(tick_to_seconds(start_tick, midi), 3),
                "endSeconds": round(tick_to_seconds(end_tick, midi), 3),
                "chord": best["chord"],
                "root": best["root"],
                "rootPc": best["rootPc"],
                "quality": best["quality"],
                "bass": best["bass"],
                "bassPc": best["bassPc"],
                "confidence": best["confidence"],
                "alternatives": candidates[1:4],
                "pitchClasses": _active_pitch_classes(weights, prefer_flats),
            }
        )

    progression = _collapse_progression(chords)
    first_tempo = midi.tempos[0].bpm if midi.tempos else 120.0

    return {
        "fileName": file_name,
        "format": midi.format_type,
        "ticksPerBeat": midi.ticks_per_beat,
        "durationTicks": midi.duration_ticks,
        "durationSeconds": round(tick_to_seconds(midi.duration_ticks, midi), 3),
        "tempoBpm": round(first_tempo, 2),
        "timeSignature": {
            "numerator": signature.numerator,
            "denominator": signature.denominator,
        },
        "keyEstimate": key_estimate | {"name": _key_name(key_estimate, prefer_flats)},
        "tracks": [
            {
                "index": track.index,
                "name": track.name,
                "noteCount": track.note_count,
                "channels": list(track.channels),
            }
            for track in midi.tracks
        ],
        "chords": chords,
        "progression": progression,
        "notes": [_public_note(note, prefer_flats, midi) for note in harmonic_notes],
    }


def _rank_chords(
    weights: list[float],
    bass_pc: int | None,
    prefer_flats: bool,
) -> list[dict[str, Any]]:
    total = sum(weights)
    unique_pitch_classes = sum(1 for weight in weights if weight > 0)
    if total <= 0 or unique_pitch_classes < 2:
        return [_no_chord(0, 0)]

    max_weight = max(weights)
    candidates = []
    for root_pc in range(12):
        for template in CHORD_TEMPLATES:
            score = _score_template(weights, root_pc, template, total, max_weight)
            if score <= 0:
                continue
            chord_name = _chord_name(root_pc, template, bass_pc, prefer_flats)
            candidates.append(
                {
                    "chord": chord_name,
                    "root": _note_name(root_pc, prefer_flats),
                    "rootPc": root_pc,
                    "quality": template.quality,
                    "bass": _note_name(bass_pc, prefer_flats) if bass_pc is not None else None,
                    "bassPc": bass_pc,
                    "confidence": round(max(0.0, min(0.99, score)), 2),
                    "_score": score,
                }
            )

    candidates.sort(key=lambda item: (item["_score"], -len(item["chord"])), reverse=True)
    cleaned = []
    seen = set()
    for candidate in candidates:
        candidate.pop("_score", None)
        if candidate["chord"] in seen:
            continue
        seen.add(candidate["chord"])
        cleaned.append(candidate)
        if len(cleaned) >= 8:
            break
    return cleaned or [_no_chord(0, 0)]


def _score_template(
    weights: list[float],
    root_pc: int,
    template: ChordTemplate,
    total: float,
    max_weight: float,
) -> float:
    template_pcs = {(root_pc + interval) % 12 for interval in template.intervals}
    chord_weight = sum(weights[pc] for pc in template_pcs)
    extra_weight = total - chord_weight
    min_present = max(total * 0.03, max_weight * 0.12)
    missing_count = sum(1 for pc in template_pcs if weights[pc] < min_present)

    coverage = chord_weight / total
    interval_strength = sum(min(1.0, weights[pc] / max_weight) for pc in template_pcs) / len(template_pcs)
    root_strength = min(1.0, weights[root_pc] / max_weight)
    extra_penalty = extra_weight / total
    size_penalty = max(0, len(template.intervals) - 3) * 0.015

    score = (
        coverage * 0.56
        + interval_strength * 0.25
        + root_strength * 0.14
        - missing_count * 0.11
        - extra_penalty * 0.08
        - size_penalty
    )
    return score


def _pitch_class_weights(notes: list[MidiNote], start_tick: int, end_tick: int) -> list[float]:
    weights = [0.0] * 12
    if end_tick <= start_tick:
        return weights
    for note in notes:
        overlap = min(note.end_tick, end_tick) - max(note.start_tick, start_tick)
        if overlap <= 0:
            continue
        weights[note.pitch % 12] += overlap * max(1, note.velocity) / 127
    return weights


def _notes_overlapping(notes: list[MidiNote], start_tick: int, end_tick: int) -> list[MidiNote]:
    return [
        note
        for note in notes
        if min(note.end_tick, end_tick) - max(note.start_tick, start_tick) > 0
    ]


def _bass_pitch_class(notes: list[MidiNote], start_tick: int, end_tick: int) -> int | None:
    bass_note: tuple[int, int] | None = None
    for note in notes:
        overlap = min(note.end_tick, end_tick) - max(note.start_tick, start_tick)
        if overlap <= 0:
            continue
        candidate = (note.pitch, overlap)
        if bass_note is None or candidate[0] < bass_note[0] or (
            candidate[0] == bass_note[0] and candidate[1] > bass_note[1]
        ):
            bass_note = candidate
    return bass_note[0] % 12 if bass_note else None


def _active_pitch_classes(weights: list[float], prefer_flats: bool) -> list[dict[str, Any]]:
    total = sum(weights)
    if total <= 0:
        return []
    result = []
    for pc, weight in enumerate(weights):
        if weight <= 0:
            continue
        result.append(
            {
                "pc": pc,
                "name": _note_name(pc, prefer_flats),
                "weight": round(weight / total, 3),
            }
        )
    return sorted(result, key=lambda item: item["weight"], reverse=True)


def _estimate_key(weights: list[float]) -> dict[str, Any]:
    if sum(weights) <= 0:
        return {"tonic": "C", "tonicPc": 0, "mode": "major", "confidence": 0.0}

    candidates = []
    for tonic_pc in range(12):
        candidates.append((tonic_pc, "major", _correlation(weights, _rotate_profile(MAJOR_PROFILE, tonic_pc))))
        candidates.append((tonic_pc, "minor", _correlation(weights, _rotate_profile(MINOR_PROFILE, tonic_pc))))
    candidates.sort(key=lambda item: item[2], reverse=True)
    best = candidates[0]
    runner_up = candidates[1]
    confidence = max(0.0, min(0.99, (best[2] - runner_up[2] + 1) / 2))
    prefer_flats = best[0] in FLAT_KEY_TONICS
    return {
        "tonic": _note_name(best[0], prefer_flats),
        "tonicPc": best[0],
        "mode": best[1],
        "confidence": round(confidence, 2),
    }


def _rotate_profile(profile: tuple[float, ...], tonic_pc: int) -> list[float]:
    return [profile[(pc - tonic_pc) % 12] for pc in range(12)]


def _correlation(a: list[float], b: list[float]) -> float:
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    centered_a = [item - mean_a for item in a]
    centered_b = [item - mean_b for item in b]
    denominator = math.sqrt(sum(item * item for item in centered_a) * sum(item * item for item in centered_b))
    if denominator == 0:
        return 0.0
    return sum(x * y for x, y in zip(centered_a, centered_b)) / denominator


def _note_name(pc: int | None, prefer_flats: bool) -> str | None:
    if pc is None:
        return None
    names = NOTE_NAMES_FLAT if prefer_flats else NOTE_NAMES_SHARP
    return names[pc % 12]


def _pitch_name(pitch: int, prefer_flats: bool) -> str:
    octave = pitch // 12 - 1
    return f"{_note_name(pitch % 12, prefer_flats)}{octave}"


def _chord_name(root_pc: int, template: ChordTemplate, bass_pc: int | None, prefer_flats: bool) -> str:
    name = f"{_note_name(root_pc, prefer_flats)}{template.suffix}"
    if bass_pc is not None and bass_pc != root_pc:
        name += f"/{_note_name(bass_pc, prefer_flats)}"
    return name


def _key_name(key_estimate: dict[str, Any], prefer_flats: bool) -> str:
    tonic = _note_name(key_estimate["tonicPc"], prefer_flats)
    mode = key_estimate["mode"]
    return f"{tonic} {mode}"


def _collapse_progression(chords: list[dict[str, Any]]) -> list[str]:
    progression = []
    previous = None
    for chord in chords:
        name = chord["chord"]
        if name == previous:
            continue
        progression.append(name)
        previous = name
    return progression


def _public_note(note: MidiNote, prefer_flats: bool, midi: MidiFileData) -> dict[str, Any]:
    return {
        "track": note.track,
        "channel": note.channel + 1,
        "pitch": note.pitch,
        "name": _pitch_name(note.pitch, prefer_flats),
        "velocity": note.velocity,
        "startTick": note.start_tick,
        "endTick": note.end_tick,
        "startSeconds": round(tick_to_seconds(note.start_tick, midi), 3),
        "endSeconds": round(tick_to_seconds(note.end_tick, midi), 3),
    }


def _no_chord(start_tick: int, end_tick: int) -> dict[str, Any]:
    return {
        "chord": "N.C.",
        "root": None,
        "rootPc": None,
        "quality": "none",
        "bass": None,
        "bassPc": None,
        "confidence": 0.0,
    }
