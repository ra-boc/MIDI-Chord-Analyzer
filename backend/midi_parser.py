from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class MidiParseError(ValueError):
    """Raised when the uploaded bytes are not a supported Standard MIDI File."""


@dataclass(frozen=True)
class MidiNote:
    track: int
    channel: int
    pitch: int
    velocity: int
    start_tick: int
    end_tick: int

    @property
    def duration_ticks(self) -> int:
        return max(0, self.end_tick - self.start_tick)


@dataclass(frozen=True)
class TempoEvent:
    tick: int
    microseconds_per_quarter: int

    @property
    def bpm(self) -> float:
        return 60_000_000 / self.microseconds_per_quarter


@dataclass(frozen=True)
class TimeSignatureEvent:
    tick: int
    numerator: int
    denominator: int


@dataclass(frozen=True)
class TrackInfo:
    index: int
    name: str
    note_count: int
    channels: tuple[int, ...]


@dataclass(frozen=True)
class MidiFileData:
    format_type: int
    ticks_per_beat: int
    notes: tuple[MidiNote, ...]
    tempos: tuple[TempoEvent, ...]
    time_signatures: tuple[TimeSignatureEvent, ...]
    tracks: tuple[TrackInfo, ...]

    @property
    def duration_ticks(self) -> int:
        if not self.notes:
            return 0
        return max(note.end_tick for note in self.notes)


def parse_midi_bytes(data: bytes) -> MidiFileData:
    if len(data) < 14 or data[:4] != b"MThd":
        raise MidiParseError("Standard MIDI File header (MThd) was not found.")

    pos = 4
    header_len = _read_u32(data, pos)
    pos += 4
    if header_len < 6:
        raise MidiParseError("MIDI header is too short.")

    format_type = _read_u16(data, pos)
    track_count = _read_u16(data, pos + 2)
    division = _read_u16(data, pos + 4)
    pos += header_len

    if division & 0x8000:
        raise MidiParseError("SMPTE time division is not supported in this MVP.")
    ticks_per_beat = division

    notes: list[MidiNote] = []
    tempos: list[TempoEvent] = []
    time_signatures: list[TimeSignatureEvent] = []
    tracks: list[TrackInfo] = []

    for track_index in range(track_count):
        if pos + 8 > len(data):
            raise MidiParseError("Unexpected end of file while reading track header.")

        chunk_type = data[pos : pos + 4]
        chunk_len = _read_u32(data, pos + 4)
        pos += 8
        chunk_end = pos + chunk_len
        if chunk_end > len(data):
            raise MidiParseError("Track chunk extends past the end of file.")

        if chunk_type != b"MTrk":
            pos = chunk_end
            continue

        track_notes, track_tempos, track_signatures, track_info = _parse_track(
            data[pos:chunk_end],
            track_index,
        )
        notes.extend(track_notes)
        tempos.extend(track_tempos)
        time_signatures.extend(track_signatures)
        tracks.append(track_info)
        pos = chunk_end

    if not tempos:
        tempos.append(TempoEvent(tick=0, microseconds_per_quarter=500_000))
    if not time_signatures:
        time_signatures.append(TimeSignatureEvent(tick=0, numerator=4, denominator=4))

    notes.sort(key=lambda note: (note.start_tick, note.end_tick, note.pitch, note.track))
    tempos = _dedupe_events(sorted(tempos, key=lambda event: event.tick))
    time_signatures = _dedupe_events(sorted(time_signatures, key=lambda event: event.tick))

    return MidiFileData(
        format_type=format_type,
        ticks_per_beat=ticks_per_beat,
        notes=tuple(notes),
        tempos=tuple(tempos),
        time_signatures=tuple(time_signatures),
        tracks=tuple(tracks),
    )


def tick_to_seconds(tick: int, midi: MidiFileData) -> float:
    current_tick = 0
    seconds = 0.0
    microseconds_per_quarter = 500_000

    for tempo in midi.tempos:
        if tempo.tick > tick:
            break
        if tempo.tick > current_tick:
            seconds += _ticks_to_seconds(
                tempo.tick - current_tick,
                midi.ticks_per_beat,
                microseconds_per_quarter,
            )
        current_tick = tempo.tick
        microseconds_per_quarter = tempo.microseconds_per_quarter

    if tick > current_tick:
        seconds += _ticks_to_seconds(
            tick - current_tick,
            midi.ticks_per_beat,
            microseconds_per_quarter,
        )

    return seconds


def _parse_track(
    data: bytes,
    track_index: int,
) -> tuple[list[MidiNote], list[TempoEvent], list[TimeSignatureEvent], TrackInfo]:
    pos = 0
    tick = 0
    running_status: int | None = None
    active_notes: dict[tuple[int, int], list[tuple[int, int]]] = {}
    notes: list[MidiNote] = []
    tempos: list[TempoEvent] = []
    time_signatures: list[TimeSignatureEvent] = []
    channels: set[int] = set()
    track_name = f"Track {track_index + 1}"

    while pos < len(data):
        delta, pos = _read_var_len(data, pos)
        tick += delta
        if pos >= len(data):
            break

        status_or_data = data[pos]
        if status_or_data < 0x80:
            if running_status is None:
                raise MidiParseError("Running status appeared before a channel event.")
            status = running_status
        else:
            status = status_or_data
            pos += 1
            if status < 0xF0:
                running_status = status
            else:
                running_status = None

        if status == 0xFF:
            if pos >= len(data):
                raise MidiParseError("Malformed MIDI meta event.")
            meta_type = data[pos]
            pos += 1
            length, pos = _read_var_len(data, pos)
            payload = data[pos : pos + length]
            pos += length

            if meta_type == 0x2F:
                break
            if meta_type in (0x03, 0x04) and payload:
                track_name = _decode_text(payload) or track_name
            elif meta_type == 0x51 and length == 3:
                microseconds = int.from_bytes(payload, "big")
                tempos.append(TempoEvent(tick=tick, microseconds_per_quarter=microseconds))
            elif meta_type == 0x58 and length >= 2:
                denominator = 2 ** payload[1]
                time_signatures.append(
                    TimeSignatureEvent(
                        tick=tick,
                        numerator=payload[0],
                        denominator=denominator,
                    )
                )
            continue

        if status in (0xF0, 0xF7):
            length, pos = _read_var_len(data, pos)
            pos += length
            continue

        event_type = status & 0xF0
        channel = status & 0x0F
        param_count = _channel_param_count(event_type)
        if pos + param_count > len(data):
            raise MidiParseError("MIDI channel event is truncated.")

        params = data[pos : pos + param_count]
        pos += param_count
        channels.add(channel + 1)

        if event_type == 0x90:
            pitch = params[0]
            velocity = params[1]
            if velocity == 0:
                _finish_note(active_notes, notes, track_index, channel, pitch, tick)
            else:
                active_notes.setdefault((channel, pitch), []).append((tick, velocity))
        elif event_type == 0x80:
            pitch = params[0]
            _finish_note(active_notes, notes, track_index, channel, pitch, tick)

    for (channel, pitch), starts in active_notes.items():
        for start_tick, velocity in starts:
            if tick > start_tick:
                notes.append(
                    MidiNote(
                        track=track_index,
                        channel=channel,
                        pitch=pitch,
                        velocity=velocity,
                        start_tick=start_tick,
                        end_tick=tick,
                    )
                )

    track_info = TrackInfo(
        index=track_index,
        name=track_name,
        note_count=len(notes),
        channels=tuple(sorted(channels)),
    )
    return notes, tempos, time_signatures, track_info


def _finish_note(
    active_notes: dict[tuple[int, int], list[tuple[int, int]]],
    notes: list[MidiNote],
    track_index: int,
    channel: int,
    pitch: int,
    end_tick: int,
) -> None:
    starts = active_notes.get((channel, pitch))
    if not starts:
        return
    start_tick, velocity = starts.pop(0)
    if not starts:
        active_notes.pop((channel, pitch), None)
    if end_tick <= start_tick:
        end_tick = start_tick + 1
    notes.append(
        MidiNote(
            track=track_index,
            channel=channel,
            pitch=pitch,
            velocity=velocity,
            start_tick=start_tick,
            end_tick=end_tick,
        )
    )


def _ticks_to_seconds(ticks: int, ticks_per_beat: int, microseconds_per_quarter: int) -> float:
    return ticks * microseconds_per_quarter / ticks_per_beat / 1_000_000


def _dedupe_events(events: Iterable):
    deduped = []
    seen_ticks: set[int] = set()
    for event in reversed(tuple(events)):
        if event.tick in seen_ticks:
            continue
        seen_ticks.add(event.tick)
        deduped.append(event)
    return list(reversed(deduped))


def _read_u16(data: bytes, pos: int) -> int:
    if pos + 2 > len(data):
        raise MidiParseError("Unexpected end of file while reading uint16.")
    return int.from_bytes(data[pos : pos + 2], "big")


def _read_u32(data: bytes, pos: int) -> int:
    if pos + 4 > len(data):
        raise MidiParseError("Unexpected end of file while reading uint32.")
    return int.from_bytes(data[pos : pos + 4], "big")


def _read_var_len(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if pos >= len(data):
            raise MidiParseError("Unexpected end of file while reading variable length value.")
        byte = data[pos]
        pos += 1
        value = (value << 7) | (byte & 0x7F)
        if byte < 0x80:
            return value, pos
    raise MidiParseError("Variable length value is too long.")


def _channel_param_count(event_type: int) -> int:
    if event_type in (0xC0, 0xD0):
        return 1
    if event_type in (0x80, 0x90, 0xA0, 0xB0, 0xE0):
        return 2
    raise MidiParseError(f"Unsupported MIDI event type: 0x{event_type:02X}")


def _decode_text(payload: bytes) -> str:
    for encoding in ("utf-8", "shift_jis", "latin-1"):
        try:
            return payload.decode(encoding).strip("\x00\r\n\t ")
        except UnicodeDecodeError:
            continue
    return ""
