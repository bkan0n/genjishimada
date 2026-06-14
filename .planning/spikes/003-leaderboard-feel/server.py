"""Spike 003 — interactive skill leaderboard (the "feel" spike).

Serves a live-tunable leaderboard over the REAL community data. Drag the weight sliders and watch
261 real players re-rank instantly; click a player to see exactly which maps earned their score;
toggle the synthetic farm profiles to watch farming resistance hold (or break at gamma=0) in real
time. Reuses Spike 002's scorer directly — a real integration handoff between spikes.

Run:
    python3 .planning/spikes/003-leaderboard-feel/server.py
    # then open http://localhost:8077
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "002-scoring-farming-resistance"))
from score import Weights, map_score, player_breakdown, profiles, score_all  # noqa: E402

ROWS = json.loads((HERE.parent / "001-skill-input-query" / "skill_inputs.json").read_text())
BY_USER: dict[int, list[dict]] = {}
for _r in ROWS:
    BY_USER.setdefault(_r["user_id"], []).append(_r)
PORT = 8077


def weights_from(payload: dict) -> Weights:
    w = Weights()
    for k in ("diff_base", "gamma", "time_bonus", "shrink_k", "wr_bonus", "partial_factor"):
        if k in payload:
            setattr(w, k, float(payload[k]))
    if "medal_gold" in payload:
        w.medal_mult = {
            "Gold": float(payload["medal_gold"]),
            "Silver": float(payload["medal_silver"]),
            "Bronze": float(payload["medal_bronze"]),
        }
    return w


def build_leaderboard(payload: dict) -> dict:
    w = weights_from(payload)
    scored = list(score_all(ROWS, w).values())
    # optionally inject synthetic farm/elite profiles so the user can see where they land
    if payload.get("include_synthetic"):
        from score import player_score  # local import keeps scorer the single source of truth
        for name, maps in profiles().items():
            scored.append({
                "user_id": f"synthetic:{name}", "name": f"★ {name}", "synthetic": True,
                "skill": player_score(maps, w), "maps": len(maps),
                "video_maps": sum(1 for m in maps if m["fully_verified"]),
                "hardest": max(m["raw_difficulty"] for m in maps),
            })
    scored.sort(key=lambda r: -r["skill"])
    for i, r in enumerate(scored, 1):
        r["pos"] = i
    return {"leaderboard": scored, "total": len(scored)}


def build_player(uid: int, payload: dict) -> dict:
    w = weights_from(payload)
    rows = BY_USER.get(uid, [])
    return {"breakdown": player_breakdown(rows, w)[:60], "name": rows[0]["name"] if rows else "?"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/api/score":
            out = build_leaderboard(payload)
        elif self.path == "/api/player":
            out = build_player(int(payload["uid"]), payload)
        else:
            self._send(404, b"{}", "application/json")
            return
        self._send(200, json.dumps(out).encode(), "application/json")


if __name__ == "__main__":
    print(f"Skill leaderboard spike — {len(BY_USER)} players, {len(ROWS)} completions")
    print(f"  open  http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
