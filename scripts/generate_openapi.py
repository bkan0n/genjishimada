#!/usr/bin/env python3
"""Generate OpenAPI specification from the Litestar app.

This script imports the Litestar app, extracts its OpenAPI schema,
and writes it to docs/openapi.json for inclusion in the documentation site.

Usage:
    python scripts/generate_openapi.py
"""

import json
import os
import sys
from pathlib import Path

# Add apps/api to Python path
repo_root = Path(__file__).parent.parent
api_path = repo_root / "apps" / "api"
sys.path.insert(0, str(api_path))

# Change to apps/api directory for imports to work correctly
original_dir = os.getcwd()
os.chdir(api_path)


def main() -> None:
    """Generate the OpenAPI spec and write to docs/openapi.json."""
    try:
        # Import the Litestar app
        print("Importing Litestar app...")
        from app import app

        # Get the OpenAPI schema
        print("Extracting OpenAPI schema...")
        openapi_schema = app.openapi_schema

        # Write to docs/openapi.json
        output_path = repo_root / "docs" / "openapi.json"
        print(f"Writing OpenAPI spec to {output_path}...")

        with output_path.open("w") as f:
            json.dump(openapi_schema.to_schema(), f, indent=2)

        print(f"✓ OpenAPI spec generated successfully at {output_path}")
        print(f"  Version: {openapi_schema.info.version}")
        print(f"  Title: {openapi_schema.info.title}")
        print(f"  Paths: {len(openapi_schema.paths)}")

    except ImportError as e:
        print(f"✗ Failed to import Litestar app: {e}", file=sys.stderr)
        print("\nMake sure you've installed the API dependencies:", file=sys.stderr)
        print("  uv sync --project apps/api", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"✗ Failed to generate OpenAPI spec: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # Restore original directory
        os.chdir(original_dir)


if __name__ == "__main__":
    main()
