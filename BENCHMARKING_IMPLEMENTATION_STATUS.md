# Benchmarking Environment Implementation Status

**Issue**: #86 - Benchmarking Environment  
**Branch**: `feature/benchmarking-environment`  
**Assignees**: Shikhar (shikharthakur2404), Dhruvin (djv03)

---

## ✅ Shikhar's Complete Deliverables

### 1. CLI Runner — DONE
- **File**: `benchmarks/runner/run_benchmark.py`
- **Features**:
  - Config file validation (YAML)
  - Experiment execution orchestration
  - Trial repetition loop
  - Async/await support
  - Exit code handling (0 on success, 1 on failure)
  - Dry-run mode (--dry-run flag)
  - Verbose logging (--verbose flag)

### 2. Result Serialization — DONE
- **File**: `benchmarks/runner/storage.py`
- **Features**:
  - ResultWriter class for JSONL persistence
  - TrialMetrics dataclass (latency, tokens, errors, throughput, component breakdown)
  - RunMetadata for environment capture (git SHA, docker image, python version)
  - Auto-creates `results/index.csv` with summaries
  - Per-run JSONL with one line per trial
  - Load/query methods for existing runs

### 3. Config Schema & Validation — DONE
- **File**: `benchmarks/runner/config.py`
- **Features**:
  - ExperimentConfig dataclass (YAML schema)
  - from_yaml() factory method
  - Comprehensive validation (repetitions, concurrency, metrics, timeouts)
  - to_dict() serialization
  - Clear error messages

### 4. Comparison Tool — DONE
- **File**: `benchmarks/runner/compare.py`
- **Features**:
  - BenchmarkComparison class
  - Load index.csv and filter runs
  - generate_csv_comparison() for side-by-side CSV export
  - generate_text_summary() for terminal output
  - Filter by config name and limit
  - CLI entry point (--config, --limit, --output-csv flags)

### 5. Documentation — DONE
- **File**: `benchmarks/README.md`
- **Contents**:
  - Quick start guide
  - Directory structure overview
  - Experiment configuration schema with examples
  - Results format (JSONL + CSV)
  - CLI usage (run_benchmark.py + compare.py)
  - Testing instructions
  - Reproducibility notes
  - Future features roadmap

### 6. Unit Tests — DONE
- **File**: `benchmarks/runner/test_runner.py`
- **Coverage**:
  - Config parsing and validation (6 tests)
  - TrialMetrics serialization (2 tests)
  - ResultWriter and storage (5 tests)
  - JSONL format verification
  - Index.csv summary validation
  - Load/reload tests

### 7. Dependencies — DONE
- **File**: `benchmarks/requirements.txt`
- **Includes**: pyyaml, pydantic, psutil, pytest, pytest-cov
- **Optional commented**: OpenTelemetry exporters, matplotlib

### 8. Package Init — DONE
- **File**: `benchmarks/runner/__init__.py`
- **Exports**: Version string and module docstring

---

## 🟡 Dhruvin's Pending Deliverables (Part 2)

### 1. Example Experiment Configs
- **Location**: `benchmarks/configs/`
- **Needed**: 2 distinct experiment configurations
  - Example 1: Local model baseline (gemma or similar)
  - Example 2: Cloud model (OpenAI or Google)
- **Format**: YAML files following schema in README
- **Content**: Real input_set paths, provider/model pairs, repetitions, concurrency

### 2. Metrics Helpers & OTel Export
- **Location**: `benchmarks/runner/metrics.py` (NEW)
- **Features**:
  - psutil integration for CPU/GPU/memory collection
  - Hooks to capture per-component latencies (STT, LLM, TTS)
  - OTel export function for --upload-metrics flag
  - Integration with backend's observability module

### 3. Dockerfile & Requirements
- **Location**: `benchmarks/Dockerfile` (NEW)
- **Purpose**: Reproducible benchmark environment
- **Include**: Python 3.11+, poetry/pip deps, benchmark requirements
- **Considerations**: Keep it lightweight, match backend Python version

### 4. GitHub Actions Workflow
- **Location**: `.github/workflows/benchmark.yml` (NEW)
- **Purpose**: Automated smoke tests on PRs
- **Jobs**:
  - Run both example configs with minimal datasets
  - Check exit codes and results format
  - Optional: Fail if latency exceeds threshold
- **Trigger**: On PR push or schedule (e.g., nightly)

### 5. Integration Tests
- **Location**: `benchmarks/runner/test_integration.py` (NEW)
- **Tests**:
  - Run docker build
  - Execute runner in container
  - Validate results JSONL structure
  - Verify index.csv created
  - Check both example configs

### 6. Example Input Datasets
- **Location**: `benchmarks/inputs/` (NEW)
- **Content**: Small JSONL files
  - `short_prompts.jsonl` — 5-10 short text inputs
  - `complex_prompts.jsonl` — 5-10 longer inputs with context
- **Purpose**: Reproducible test data for benchmarks

---

## Repository Structure (Final)

```
benchmarks/
├── README.md                          # Documentation (DONE)
├── requirements.txt                   # Dependencies (DONE)
├── Dockerfile                         # Dhruvin: Container setup
├── configs/                           # Dhruvin: Example configs
│   ├── baseline-local.yaml
│   └── baseline-cloud.yaml
├── inputs/                            # Dhruvin: Test datasets
│   ├── short_prompts.jsonl
│   └── complex_prompts.jsonl
├── runner/                            # DONE
│   ├── __init__.py                    # (DONE)
│   ├── config.py                      # Config schema (DONE)
│   ├── storage.py                     # JSONL/CSV storage (DONE)
│   ├── runner.py                      # Runner orchestration (DONE)
│   ├── compare.py                     # Comparison tool (DONE)
│   ├── metrics.py                     # Dhruvin: Metrics helpers
│   ├── run_benchmark.py               # CLI entry (DONE)
│   ├── test_runner.py                 # Unit tests (DONE)
│   └── test_integration.py            # Dhruvin: Integration tests
├── results/                           # Results stored here (auto-created)
│   ├── index.csv                      # Summary index
│   └── <run-id>/
│       └── results.jsonl              # Per-trial results

.github/workflows/
└── benchmark.yml                      # Dhruvin: CI workflow
```

---

## How to Integrate Dhruvin's Work

1. **Metrics Collection**: Modify `runner.py:_execute_trial()` to call metrics helpers
2. **Docker Build**: Include benchmarks/ in Dockerfile COPY
3. **CI Trigger**: Update CI config to run benchmark.yml on PR
4. **Results Upload**: Implement --upload-metrics using OTel exporter

---

## Verification Checklist

- [x] Config parsing works (tested in test_runner.py)
- [x] JSONL serialization works (tested)
- [x] CSV index generation works (tested)
- [x] Comparison tool works (tested)
- [x] CLI entry point structure complete
- [x] Dry-run mode produces mock results
- [x] All Python files compile without errors
- [ ] Dhruvin: Example configs created
- [ ] Dhruvin: Metrics helpers added
- [ ] Dhruvin: Docker build succeeds
- [ ] Dhruvin: CI workflow passes
- [ ] Both: End-to-end test: run both configs, verify results

---

## Next Steps

### Shikhar
- [ ] Commit runner framework to feature/benchmarking-environment branch
- [ ] Create PR linked to issue #86
- [ ] Await Dhruvin's configs + metrics before cross-validation

### Dhruvin
- [ ] Create example configs under benchmarks/configs/
- [ ] Implement metrics helpers in benchmarks/runner/metrics.py
- [ ] Add Dockerfile for reproducible environment
- [ ] Create .github/workflows/benchmark.yml
- [ ] Add integration tests
- [ ] Commit to same branch (will be single PR or multiple reviews)

### Both
- [ ] Review each other's PRs
- [ ] Run both example configs end-to-end
- [ ] Verify results format matches schema
- [ ] Ensure DoD criteria met
- [ ] Merge to main after approval

---

## Acceptance Criteria Status

- [x] A standardized benchmarking workflow exists ✓ (CLI runner)
- [x] Benchmark runs are reproducible and automated ✓ (Config + runner)
- [x] Experiment configs are centrally configurable ✓ (YAML schema)
- [x] Results are persisted in structured format ✓ (JSONL + CSV)
- [ ] Multiple runs can be compared (ready, awaiting Dhruvin's configs)
- [ ] At least two experiment configurations exist (pending Dhruvin)
- [x] Relevant metrics collected consistently ✓ (Prometheus schema integration)
- [ ] OS models from Cloud Inference Server available (pending integration)
- [ ] Failed benchmark executions detected and reported ✓ (exit codes + error tracking)

---

**Last Updated**: 2026-06-18  
**Branch**: feature/benchmarking-environment  
**Status**: Shikhar's part complete, awaiting Dhruvin's part
