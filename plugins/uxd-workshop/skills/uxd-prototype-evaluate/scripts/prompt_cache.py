"""Provider-neutral prompt-prefix measurement helpers."""

from __future__ import annotations

import hashlib


def prefix_metrics(static_prefix: str, dynamic_suffix: str) -> dict[str, int | str]:
    static_bytes = static_prefix.encode()
    dynamic_bytes = dynamic_suffix.encode()
    return {
        "static_prefix_sha256": f"sha256:{hashlib.sha256(static_bytes).hexdigest()}",
        "static_prefix_bytes": len(static_bytes),
        "dynamic_input_bytes": len(dynamic_bytes),
    }
