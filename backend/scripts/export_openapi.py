"""Write the API contract to docs/openapi.json."""

import json
from pathlib import Path

from tunnelgate.app import openapi_schema

out = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
out.write_text(json.dumps(openapi_schema(), indent=2, sort_keys=True) + "\n")
print(f"wrote {out}")
