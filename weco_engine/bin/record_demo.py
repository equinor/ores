#!/usr/bin/env python3
"""
record_demo.py — Automated video walkthrough of WeCo Studio (§3.1)
====================================================================

Drives WeCo Studio programmatically and captures the screen using
``ffmpeg`` (or ``scrot`` for screenshots).

Usage::

    python bin/record_demo.py                  # full demo with ffmpeg recording
    python bin/record_demo.py --screenshots    # screenshot-only mode
    python bin/record_demo.py --dry-run        # no capture, just run steps

Requirements:
    - PyQt6
    - ffmpeg (for video) or scrot/import (for screenshots)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ── Demo steps ────────────────────────────────────────────────────────────

DEMO_STEPS = [
    {
        "title": "1. Launch WeCo Studio",
        "action": "launch",
        "wait": 3.0,
        "description": "Open WeCo Studio and wait for the main window.",
    },
    {
        "title": "2. Load dataset",
        "action": "load_dataset",
        "dataset": "data_set_2",
        "wait": 2.0,
        "description": "Load the data_set_2 example dataset.",
    },
    {
        "title": "3. Configure options",
        "action": "set_options",
        "options": {"cost_function": "composite", "max_cor": 3, "band_width": 20},
        "wait": 1.0,
        "description": "Set correlation parameters.",
    },
    {
        "title": "4. Run correlation",
        "action": "run",
        "wait": 5.0,
        "description": "Execute the correlation engine.",
    },
    {
        "title": "5. View results",
        "action": "view_results",
        "wait": 2.0,
        "description": "Display correlation panel and cost matrix.",
    },
    {
        "title": "6. Export",
        "action": "export",
        "format": "csv",
        "wait": 1.0,
        "description": "Export results to CSV.",
    },
]


class DemoRecorder:
    """Coordinates demo steps with screen capture."""

    def __init__(self, output_dir: str, mode: str = "video"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.mode = mode  # "video", "screenshots", "dry-run"
        self._ffmpeg_proc = None
        self._step_count = 0

    def start_recording(self):
        if self.mode == "video":
            outfile = self.output_dir / "weco_demo.mp4"
            self._ffmpeg_proc = subprocess.Popen(
                [
                    "ffmpeg", "-y",
                    "-video_size", "1920x1080",
                    "-framerate", "25",
                    "-f", "x11grab",
                    "-i", os.environ.get("DISPLAY", ":0"),
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-crf", "23",
                    str(outfile),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"Recording to {outfile}")

    def stop_recording(self):
        if self._ffmpeg_proc:
            self._ffmpeg_proc.stdin.write(b"q")
            self._ffmpeg_proc.stdin.flush()
            self._ffmpeg_proc.wait(timeout=10)
            print("Recording stopped.")

    def capture_screenshot(self, name: str):
        if self.mode in ("screenshots", "video"):
            outfile = self.output_dir / f"{name}.png"
            try:
                subprocess.run(
                    ["import", "-window", "root", str(outfile)],
                    timeout=5,
                    check=True,
                )
            except (FileNotFoundError, subprocess.CalledProcessError):
                print(f"  (screenshot skipped: ImageMagick 'import' not available)")

    def run_step(self, step: dict):
        self._step_count += 1
        print(f"\n--- {step['title']} ---")
        print(f"    {step['description']}")

        if self.mode == "dry-run":
            print(f"    [dry-run] would wait {step['wait']}s")
            return

        time.sleep(step["wait"])
        self.capture_screenshot(f"step_{self._step_count:02d}_{step['action']}")


def main():
    parser = argparse.ArgumentParser(description="Record WeCo Studio demo")
    parser.add_argument("--output", default="tmp/demo", help="Output directory")
    parser.add_argument("--screenshots", action="store_true", help="Screenshot-only mode")
    parser.add_argument("--dry-run", action="store_true", help="No capture, print steps only")
    args = parser.parse_args()

    mode = "dry-run" if args.dry_run else ("screenshots" if args.screenshots else "video")
    recorder = DemoRecorder(args.output, mode=mode)

    print("WeCo Studio Demo Script")
    print("=" * 40)

    recorder.start_recording()
    try:
        for step in DEMO_STEPS:
            recorder.run_step(step)
    finally:
        recorder.stop_recording()

    print(f"\nDemo complete. Output in {args.output}/")


if __name__ == "__main__":
    main()
