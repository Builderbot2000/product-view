# Product View -- the pipeline in a CPU-only Linux container.
#
#   docker compose build
#   docker compose run --rm pv run            # full pipeline, clean database
#   docker compose run --rm pv painpoints --top 15
#
# Data (archive + databases) and models are volumes, never baked in: the image
# stays code-only and a rebuild never touches the corpus.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # platformdirs puts the model cache under $XDG_CACHE_HOME on Linux, so
    # this is where the ~390 MB of downloaded models land -- a named volume.
    XDG_CACHE_HOME=/cache

WORKDIR /app

# CPU torch first. Plain PyPI on Linux resolves torch to the ~2.5 GB CUDA
# build; the CPU index keeps the image at a fraction of that.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

# Dependencies before source, so editing code does not reinstall the stack.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
 && pip install -r /tmp/requirements.txt

COPY src ./src
RUN pip install --no-deps .

COPY config.yaml ./

ENTRYPOINT ["pv"]
CMD ["run"]
