# Product View: one image that runs one cycle and exits (docs/production-plan.md §0).
#
#   docker build -t product-view .                         # models download on first run
#   docker build -t product-view --build-arg BAKE_MODELS=1 .   # models inside, for air-gapped hosts
#
#   docker run --rm -v pv-data:/app/data -v pv-models:/cache --env-file .env product-view
#   docker run --rm ... product-view check-matching       # acceptance check, before go-live
#
# CPU only; the host's scheduler decides when it runs. It writes only to:
#   /app/data  the one persistent volume: archive, databases, lock, built pages
#   /cache     model weights downloaded on first use (not needed with BAKE_MODELS=1)
#   /tmp       scratch
# so it runs with a read-only root filesystem. Configuration comes only from
# mounts and environment variables; there are no credentials in the image:
#   /app/config.yaml   mount over the copy baked in
#   matrix             PV_MATRIX=/path/to/a/mounted/matrix.yaml (default: the sample)
#   secrets            CONFLUENCE_BASE_URL, CONFLUENCE_USER, ATLASSIAN_TOKEN,
#                      PV_LLM_BASE_URL, PV_LLM_API_KEY
#   corporate network  HTTPS_PROXY / NO_PROXY; SSL_CERT_FILE and REQUESTS_CA_BUNDLE
#                      for a TLS-inspecting proxy's CA (mount the bundle)
#   model mirror       HF_ENDPOINT=https://<in-house artifact store> to download
#                      the weights from a mirror instead of huggingface.co

FROM python:3.12-slim

ARG BAKE_MODELS=

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Model weights: Hugging Face's cache (Qwen3 embedding, MiniLM) and
    # platformdirs' (opus-mt), both under /cache.
    XDG_CACHE_HOME=/cache \
    HF_HOME=/cache/huggingface \
    # Baked images never reach for the network for weights ("" leaves it off).
    HF_HUB_OFFLINE=${BAKE_MODELS:+1} \
    HOME=/tmp \
    NUMBA_CACHE_DIR=/tmp/numba

WORKDIR /app

# Pinned dependencies, CPU torch included (its index is named in the lock),
# before the source, so editing code does not reinstall the stack.
COPY requirements.lock ./
RUN pip install -r requirements.lock

COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-deps . && rm -rf src build

# About 1.6 GB: Qwen3-Embedding-0.6B (1.2 GB) and MiniLM (90 MB) for matching,
# opus-mt-fr-en (300 MB) for the cycle's translation step, so French reviews
# never need a download either.
RUN if [ -n "$BAKE_MODELS" ]; then \
      HF_HUB_OFFLINE= python -c "from sentence_transformers import SentenceTransformer as S; \
from product_view.topics.embed import QWEN, MINILM; \
S(QWEN, device='cpu'); S('sentence-transformers/' + MINILM, device='cpu'); \
from product_view.lang.translate import _model; _model()" \
      && chmod -R a+rX /cache; \
    else mkdir -p /cache; fi

COPY config.yaml matrix.sample.yaml ./

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin pv \
 && mkdir -p /app/data \
 && chown pv /app/data \
 && if [ -z "$BAKE_MODELS" ]; then chown pv /cache; fi
USER 10001

VOLUME ["/app/data"]
ENTRYPOINT ["pv"]
# The built pages go in the data volume, so the root filesystem stays read-only.
CMD ["cycle", "--out", "data/report"]
