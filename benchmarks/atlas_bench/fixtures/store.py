"""Deterministic fixtures for benchmark scenarios.

Fixtures provide reproducible input data for benchmark scenarios.
Each fixture is versioned and has a content digest for integrity verification.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml  # type: ignore[import-untyped]


@dataclass(frozen=True)
class FixtureMetadata:
    """Metadata for a benchmark fixture."""

    fixture_id: str
    name: str
    description: str
    version: str
    content_digest: str  # SHA-256 of the fixture content
    format: str  # json, yaml, csv, text
    size_bytes: int
    tags: tuple[str, ...] = ()


class FixtureStore:
    """Manages deterministic fixtures for benchmark scenarios."""

    def __init__(self, fixtures_dir: Path) -> None:
        self._fixtures_dir = fixtures_dir
        self._fixtures_dir.mkdir(parents=True, exist_ok=True)
        self._metadata: dict[str, FixtureMetadata] = {}
        self._index_path = fixtures_dir / "fixtures.yaml"
        self._load_index()

    def _load_index(self) -> None:
        """Load fixture index from disk."""
        if self._index_path.exists():
            with self._index_path.open() as f:
                data = yaml.safe_load(f) or {}
            for item in data.get("fixtures", []):
                meta = FixtureMetadata(**item)
                self._metadata[meta.fixture_id] = meta

    def _save_index(self) -> None:
        """Save fixture index to disk."""
        data = {
            "fixtures": [
                {
                    "fixture_id": m.fixture_id,
                    "name": m.name,
                    "description": m.description,
                    "version": m.version,
                    "content_digest": m.content_digest,
                    "format": m.format,
                    "size_bytes": m.size_bytes,
                    "tags": list(m.tags),
                }
                for m in self._metadata.values()
            ]
        }
        with self._index_path.open("w") as f:
            yaml.safe_dump(data, f, sort_keys=True)

    def _compute_digest(self, content: bytes) -> str:
        """Compute SHA-256 digest of content."""
        return "sha256:" + hashlib.sha256(content).hexdigest()

    def register(
        self,
        fixture_id: str,
        name: str,
        description: str,
        content: Any,
        format: str = "json",
        version: str = "1.0",
        tags: tuple[str, ...] = (),
    ) -> FixtureMetadata:
        """Register a fixture with deterministic content."""
        if format == "json":
            content_bytes = json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        elif format == "yaml":
            content_bytes = yaml.dump(content, sort_keys=True).encode()
        elif format == "csv":
            content_bytes = str(content).encode()
        elif format == "text":
            content_bytes = str(content).encode()
        else:
            raise ValueError(f"Unsupported format: {format}")

        digest = self._compute_digest(content_bytes)
        size = len(content_bytes)

        # Write fixture file
        fixture_path = self._fixtures_dir / f"{fixture_id}.{format}"
        fixture_path.write_bytes(content_bytes)

        # Register metadata
        meta = FixtureMetadata(
            fixture_id=fixture_id,
            name=name,
            description=description,
            version=version,
            content_digest=digest,
            format=format,
            size_bytes=size,
            tags=tags,
        )
        self._metadata[fixture_id] = meta
        self._save_index()

        return meta

    def load(self, fixture_id: str) -> Any:
        """Load a fixture by ID."""
        meta = self._metadata.get(fixture_id)
        if not meta:
            raise KeyError(f"Fixture {fixture_id} not found")

        fixture_path = self._fixtures_dir / f"{fixture_id}.{meta.format}"
        if not fixture_path.exists():
            raise FileNotFoundError(f"Fixture file not found: {fixture_path}")

        content_bytes = fixture_path.read_bytes()
        actual_digest = self._compute_digest(content_bytes)
        if actual_digest != meta.content_digest:
            raise ValueError(
                f"Fixture {fixture_id} digest mismatch: "
                f"expected {meta.content_digest}, got {actual_digest}"
            )

        if meta.format == "json":
            return json.loads(content_bytes)
        elif meta.format == "yaml":
            return yaml.safe_load(content_bytes)
        elif meta.format in ("csv", "text"):
            return content_bytes.decode()
        else:
            raise ValueError(f"Unsupported format: {meta.format}")

    def load_raw(self, fixture_id: str) -> bytes:
        """Load raw fixture bytes."""
        meta = self._metadata.get(fixture_id)
        if not meta:
            raise KeyError(f"Fixture {fixture_id} not found")

        fixture_path = self._fixtures_dir / f"{fixture_id}.{meta.format}"
        return fixture_path.read_bytes()

    def get_metadata(self, fixture_id: str) -> Optional[FixtureMetadata]:
        """Get fixture metadata."""
        return self._metadata.get(fixture_id)

    def list_fixtures(self) -> list[FixtureMetadata]:
        """List all registered fixtures."""
        return list(self._metadata.values())

    def verify_all(self) -> dict[str, bool]:
        """Verify all fixtures against their digests."""
        results = {}
        for fixture_id in self._metadata:
            try:
                self.load(fixture_id)
                results[fixture_id] = True
            except Exception:
                results[fixture_id] = False
        return results


# Pre-defined fixtures for benchmark scenarios
DEFAULT_FIXTURES: dict[str, dict[str, Any]] = {
    "csv_dataset_simple": {
        "fixture_id": "csv_dataset_simple",
        "name": "Simple CSV Dataset",
        "description": "A small deterministic CSV dataset for analysis tasks",
        "content": (
            "id,value,category\n"
            "1,10.5,A\n"
            "2,20.3,B\n"
            "3,15.7,A\n"
            "4,30.1,C\n"
            "5,25.9,B\n"
            "6,18.2,A\n"
            "7,22.4,B\n"
            "8,28.6,C\n"
        ),
        "format": "csv",
        "tags": ("demo", "csv", "statistics"),
    },
    "csv_dataset_medium": {
        "fixture_id": "csv_dataset_medium",
        "name": "Medium CSV Dataset",
        "description": "A medium-sized deterministic CSV dataset with multiple columns",
        "content": (
            "id,measurement,timestamp,group,quality\n"
            "1,12.34,2024-01-01T00:00:00Z,control,high\n"
            "2,15.67,2024-01-01T01:00:00Z,control,high\n"
            "3,11.89,2024-01-01T02:00:00Z,control,medium\n"
            "4,18.23,2024-01-01T00:00:00Z,treatment,high\n"
            "5,16.45,2024-01-01T01:00:00Z,treatment,high\n"
            "6,19.12,2024-01-01T02:00:00Z,treatment,medium\n"
            "7,13.56,2024-01-01T03:00:00Z,control,high\n"
            "8,17.89,2024-01-01T03:00:00Z,treatment,high\n"
            "9,14.78,2024-01-01T04:00:00Z,control,low\n"
            "10,20.01,2024-01-01T04:00:00Z,treatment,high\n"
        ),
        "format": "csv",
        "tags": ("demo", "csv", "statistics", "grouped"),
    },
    "json_schema_valid": {
        "fixture_id": "json_schema_valid",
        "name": "Valid JSON Schema Input",
        "description": "A valid JSON object matching a tool's input schema",
        "content": {
            "dataset_path": "data/sample.csv",
            "operations": ["mean", "std", "min", "max"],
            "group_by": "category",
        },
        "format": "json",
        "tags": ("demo", "json", "schema"),
    },
    "malformed_json": {
        "fixture_id": "malformed_json",
        "name": "Malformed JSON Input",
        "description": "Invalid JSON that should be rejected by validation",
        "content": "{invalid json: missing quotes}",
        "format": "text",
        "tags": ("security", "malformed"),
    },
    "path_traversal_attempt": {
        "fixture_id": "path_traversal_attempt",
        "name": "Path Traversal Attempt",
        "description": "Input attempting directory traversal",
        "content": {
            "dataset_path": "../../../etc/passwd",
            "operations": ["mean"],
        },
        "format": "json",
        "tags": ("security", "path_traversal"),
    },
    "unauthorized_tool_request": {
        "fixture_id": "unauthorized_tool_request",
        "name": "Unauthorized Tool Request",
        "description": "Request for a tool the agent is not granted access to",
        "content": {
            "tool_id": "admin_delete_all_data",
            "arguments": {},
        },
        "format": "json",
        "tags": ("security", "unauthorized"),
    },
    "network_access_attempt": {
        "fixture_id": "network_access_attempt",
        "name": "Network Access Attempt",
        "description": "Tool arguments attempting network access",
        "content": {
            "url": "http://external-service/api/data",
            "method": "GET",
        },
        "format": "json",
        "tags": ("security", "network"),
    },
    "large_resource_request": {
        "fixture_id": "large_resource_request",
        "name": "Large Resource Request",
        "description": "Request designed to trigger resource exhaustion",
        "content": {
            "size_mb": 1000,
            "iterations": 1000000,
        },
        "format": "json",
        "tags": ("security", "resource_exhaustion"),
    },
    "replay_attack_payload": {
        "fixture_id": "replay_attack_payload",
        "name": "Replay Attack Payload",
        "description": "A previously captured valid invocation for replay testing",
        "content": {
            "tool_id": "csv_statistics",
            "arguments": {"dataset_path": "data/sample.csv", "operations": ["mean"]},
            "invocation_id": "inv-replay-test-12345",
        },
        "format": "json",
        "tags": ("security", "replay"),
    },
}


def create_default_fixtures(fixtures_dir: Path) -> FixtureStore:
    """Create and populate the default fixture store."""
    store = FixtureStore(fixtures_dir)
    for fixture_data in DEFAULT_FIXTURES.values():
        store.register(**fixture_data)
    return store
