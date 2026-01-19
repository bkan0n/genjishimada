# OCR Service

The OCR service extracts player name, run time, and map code from Overwatch parkour screenshots. It is implemented in the [`genjishimada-ocr`](https://github.com/bkan0n/genjishimada-ocr) repository and is consumed by the API during completion submission flows.

## Purpose

The OCR service processes parkour screenshots and returns structured data including the player's name, run time (seconds), and map code. It also returns raw extracted text for debugging.

## Key features

- **Multi-language OCR** with prewarmed models (English, Chinese, Korean, Japanese).
- **Script-aware name selection** to choose the most plausible player name.
- **Robust time parsing** with error correction for common OCR misreads.
- **Flexible map code extraction** using explicit and generic patterns.

## API endpoints

| Method & Path | Description |
|--------------|-------------|
| `GET /ping` | Returns `{ "ok": true, "models": [...] }` and readiness info. |
| `POST /extract` | Accepts `{ "image_b64": "data:image/png;base64,..." }` and returns extracted data. |

Interactive documentation is available at `/docs` (Swagger UI) and `/redoc` on the OCR service.

## Deployment & quickstart

The OCR service runs independently and is not deployed by this repo. See the [`genjishimada-ocr`](https://github.com/bkan0n/genjishimada-ocr) repository for Docker and local Python setup details.
