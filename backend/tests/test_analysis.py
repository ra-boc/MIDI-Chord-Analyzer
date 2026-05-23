from __future__ import annotations

import unittest

from backend.chord_analysis import analyze_midi
from backend.midi_parser import parse_midi_bytes


TPQ = 480
BAR = TPQ * 4


class MidiAnalysisTest(unittest.TestCase):
    def test_detects_basic_pop_progression(self) -> None:
        midi = parse_midi_bytes(
            make_midi(
                [
                    (0, BAR, [60, 64, 67]),
                    (BAR, BAR * 2, [57, 60, 64]),
                    (BAR * 2, BAR * 3, [53, 57, 60]),
                    (BAR * 3, BAR * 4, [55, 59, 62, 65]),
                ]
            )
        )
        result = analyze_midi(midi, file_name="progression.mid")
        chords = [segment["chord"] for segment in result["chords"]]

        self.assertEqual(chords[:4], ["C", "Am", "F", "G7"])
        self.assertEqual(result["timeSignature"], {"numerator": 4, "denominator": 4})
        self.assertEqual(result["tempoBpm"], 120.0)

    def test_ignores_drum_channel(self) -> None:
        midi = parse_midi_bytes(
            make_midi(
                [(0, BAR, [60, 64, 67])],
                drum_hits=[(0, 240, 36), (240, 480, 38)],
            )
        )
        result = analyze_midi(midi, file_name="drums.mid")

        self.assertEqual(result["chords"][0]["chord"], "C")
        self.assertTrue(all(note["channel"] != 10 for note in result["notes"]))


def make_midi(
    chords: list[tuple[int, int, list[int]]],
    drum_hits: list[tuple[int, int, int]] | None = None,
) -> bytes:
    events: list[tuple[int, bytes]] = [
        (0, b"\xff\x51\x03\x07\xa1\x20"),
        (0, b"\xff\x58\x04\x04\x02\x18\x08"),
    ]

    for start, end, pitches in chords:
        for pitch in pitches:
            events.append((start, bytes([0x90, pitch, 96])))
        for pitch in pitches:
            events.append((end, bytes([0x80, pitch, 0])))

    for start, end, pitch in drum_hits or []:
        events.append((start, bytes([0x99, pitch, 100])))
        events.append((end, bytes([0x89, pitch, 0])))

    events.sort(key=lambda item: item[0])
    track = bytearray()
    current_tick = 0
    for tick, payload in events:
        track.extend(write_var_len(tick - current_tick))
        track.extend(payload)
        current_tick = tick
    track.extend(write_var_len(0))
    track.extend(b"\xff\x2f\x00")

    header = b"MThd" + (6).to_bytes(4, "big")
    header += (0).to_bytes(2, "big")
    header += (1).to_bytes(2, "big")
    header += TPQ.to_bytes(2, "big")
    return header + b"MTrk" + len(track).to_bytes(4, "big") + bytes(track)


def write_var_len(value: int) -> bytes:
    buffer = value & 0x7F
    value >>= 7
    while value:
        buffer <<= 8
        buffer |= ((value & 0x7F) | 0x80)
        value >>= 7

    result = bytearray()
    while True:
        result.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            break
    return bytes(result)


if __name__ == "__main__":
    unittest.main()
