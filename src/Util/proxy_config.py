"""Validate Uvicorn's explicit transport-level proxy trust configuration."""

from __future__ import annotations

import ipaddress
import os


def validate_forwarded_allow_ips(value: str | None = None) -> str:
    raw = os.environ.get("FORWARDED_ALLOW_IPS", "") if value is None else value
    if not raw.strip():
        return ""
    entries = []
    for item in raw.split(","):
        item = item.strip()
        try:
            network = ipaddress.ip_network(item, strict=False)
        except ValueError as exc:
            raise ValueError("FORWARDED_ALLOW_IPS must contain explicit proxy IP addresses or CIDRs; wildcard trust is forbidden") from exc
        if network.prefixlen == 0:
            raise ValueError("FORWARDED_ALLOW_IPS cannot trust every address")
        entries.append(str(network) if "/" in item else str(network.network_address))
    return ",".join(entries)


if __name__ == "__main__":
    print(validate_forwarded_allow_ips())
