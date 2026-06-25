# TaskOrbit Benchmark Runner — Docker image
#
# Provides a reproducible, isolated environment for running benchmark
# experiments. Mount a results directory to persist output outside the
# container; pass API keys via environment variables (never bake them in).
#
# Build:
#   docker build -t taskorbit-bench .
#
# Run (dry-run, no API keys needed):
#   docker run taskorbit-bench --config configs/baseline-local.yaml --dry-run
#
# Run (real, cloud provider):
#   docker run \
#     -e OPENAI_API_KEY=$OPENAI_API_KEY \
#     -v $(pwd)/results:/app/results \
#     taskorbit-bench --config configs/baseline-cloud.yaml
#
# Run (real, open-source via OpenRouter):
#   docker run \
#     -e OPENROUTER_API_KEY=$OPENROUTER_API_KEY \
#     -v $(pwd)/results:/app/results \
#     taskorbit-bench --config configs/baseline-local.yaml

FROM python:3.11-slim

# git is needed by BenchmarkRunner._get_git_sha()
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies before copying source so this layer is cached
# when only source files change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire benchmarks directory into /app
COPY . .

# runner/ contains the modules imported by run_benchmark.py using bare names
# (e.g. `from config import ...`), so add it to PYTHONPATH.
ENV PYTHONPATH=/app/runner

# Results are written to /app/results by default; mount a host directory
# here to persist them: -v $(pwd)/results:/app/results
VOLUME ["/app/results"]

# The entry point is the CLI runner; callers supply --config and other flags.
ENTRYPOINT ["python", "runner/run_benchmark.py", "--results-dir", "/app/results"]
CMD ["--help"]
