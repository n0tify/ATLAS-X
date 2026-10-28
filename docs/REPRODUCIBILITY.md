# Reproducibility Standards for ATLAS-BENCH

## Core Principle

> **Two identical experiment configurations must produce equivalent manifests and comparable results.**

## Reproducibility Requirements

### 1. Deterministic Experiment ID

The experiment ID is a deterministic hash of the configuration:
```python
config_data = {
    "scenario_ids": sorted(scenario_ids),
    "baselines": sorted(b.value for b in baseline_configurations),
    "ablations": sorted(a.value for a in ablation_modes),
    "model": model_identifier,
    "seed": random_seed,
    "git_commit": git_commit,
    "tool_registry_version": tool_registry_version,
    "timestamp": timestamp,
}
config_hash = sha256(json.dumps(config_data, sort_keys=True)).hexdigest()[:16]
experiment_id = f"exp_{config_hash}"
```

**Property**: Same config → Same ID → Same manifest

### 2. Complete Configuration Capture

Every ExperimentConfiguration records:

| Field | Source | Purpose |
|-------|--------|---------|
| `git_commit` | `git rev-parse HEAD` | Code version |
| `benchmark_version` | Package version | Benchmark schema |
| `software_version` | Application version | ATLAS-X version |
| `python_version` | `sys.version` | Runtime |
| `platform_info` | `platform.system/release` | OS |
| `model_identifier` | Config | LLM model |
| `random_seed` | Config | Stochastic control |
| `scenario_versions` | Registry | Scenario definitions |
| `tool_registry_version` | Registry | Tool definitions |
| `limits` | Settings | Resource bounds |
| `environment` | `os.environ` | Env vars |

### 3. Deterministic Fixtures

All input fixtures are:
- **Versioned**: `fixture_id@v1.0`
- **Content-addressed**: SHA-256 digest stored in metadata
- **Verified on load**: Digest mismatch = error
- **Immutable**: Never modified after creation

```python
fixture_meta = FixtureMetadata(
    fixture_id="csv_dataset_simple",
    version="1.0",
    content_digest="sha256:abc123...",
    format="csv",
    size_bytes=1024,
)
```

### 4. Manifest Integrity

The ExperimentManifest provides end-to-end verification:
```python
manifest = ExperimentManifest(
    experiment_id=config.experiment_id,
    configuration=config,
    scenario_definitions={...},
    fixture_digests={...},
    software_hash=compute_source_hash(),
    git_commit=git_commit,
    environment_snapshot={...},
    manifest_hash="",  # Computed from all above
)
```

**Verification**: `manifest.verify()` recomputes hash and compares.

### 5. Result Integrity

Results are protected from corruption:
- **JSONL**: Append-only, one record per line
- **SQLite**: Structured, transactional
- **Digests**: Input, config, and result digests recorded
- **No UI edits**: Benchmark results are read-only in UI

## Reproduction Procedure

### To Reproduce an Experiment

1. **Check out the exact commit**:
   ```bash
   git checkout <manifest.configuration.git_commit>
   ```

2. **Install dependencies**:
   ```bash
   pip install -e .  # Same versions via lockfile
   ```

3. **Set environment**:
   ```bash
   export ATLAS_MODEL_BASE_URL=http://127.0.0.1:11434
   export ATLAS_MODEL_NAME=llama3.1:8b
   # ... other ATLAS_* vars from manifest.environment_snapshot
   ```

4. **Run with same configuration**:
   ```python
   runner = ExperimentRunner(output_dir)
   config = manifest.configuration  # From saved manifest
   results = runner.run_experiment(config, runner_fn)
   ```

5. **Verify manifest matches**:
   ```python
   new_manifest = runner.create_manifest(config, scenario_defs)
   assert new_manifest.manifest_hash == manifest.manifest_hash
   ```

### Reproducibility Checklist

- [ ] Same git commit
- [ ] Same Python version
- [ ] Same dependencies (pip freeze)
- [ ] Same model endpoint and model
- [ ] Same random seed
- [ ] Same resource limits
- [ ] Same fixture digests
- [ ] Same scenario definitions
- [ ] Same tool registry version

## Sources of Non-Determinism

### Acceptable (documented)
- LLM output variance (controlled by seed, but model may not be fully deterministic)
- System scheduling (affects latency)
- Sandbox resource contention

### Unacceptable (must be eliminated)
- Random experiment IDs
- Unrecorded configuration
- Mutable fixtures
- Race conditions in result recording
- Clock-dependent behavior

## Handling Non-Determinism

### LLM Variance
- Fix `model_temperature=0` if supported
- Use `random_seed` for any stochastic components
- Run multiple trials, report distribution
- Label single-trial results as exploratory

### Latency Variance
- Report median, not mean
- Report p95, std
- Run sufficient trials (N ≥ 30 for statistics)
- Document host conditions

### Sandbox Variance
- Warm up sandbox before benchmarks
- Report sandbox health metrics
- Exclude cold-start runs

## Versioning

### Benchmark Version
- `MAJOR.MINOR.PATCH`
- MAJOR: Breaking schema changes
- MINOR: New scenarios/metrics
- PATCH: Bug fixes, documentation

### Scenario Version
- Each scenario has `version` field
- Incremented when expected outcomes change
- Recorded in experiment manifest

### Fixture Version
- Each fixture has `version` field
- Incremented when content changes
- Digest changes with content

## Archival

### Long-term Storage
- Manifests: Permanent, immutable
- Results: Permanent, append-only
- Fixtures: Permanent, versioned
- Source code: Git history

### Reproducibility Package
For publication, bundle:
```
reproducibility_package/
├── manifest.json           # Experiment manifest
├── results.jsonl           # All results
├── metrics.jsonl           # All metrics
├── fixtures/               # All input fixtures
├── source_snapshot/        # Git archive at commit
├── environment.txt         # Environment snapshot
└── REPRODUCE.md           # Reproduction instructions
```

## CI/CD Verification

Automated reproducibility checks:
```yaml
# .github/workflows/reproducibility.yml
- name: Verify manifest integrity
  run: python -m benchmarks.atlas_bench.runner.verify_manifests

- name: Reproduce reference experiment
  run: |
    python -m benchmarks.atlas_bench.runner.reproduce \
      --manifest-path reference/manifest.json \
      --output reproduce/
    python -m benchmarks.atlas_bench.runner.compare \
      --original reference/results.jsonl \
      --reproduced reproduce/results.jsonl
```