# ============================================================
# Dockerfile - paperfetch CLI
#
#   docker build -t paperfetch .
#   docker run --rm -v "$PWD/out:/work" paperfetch paper lookup --doi 10.1038/s41586-020-2649-2
#
# 可选 API Key 通过 --env-file 传入（不要把密钥写进镜像）：
#   docker run --rm --env-file ./secrets.env paperfetch doctor
# ============================================================
FROM python:3.12-slim

WORKDIR /app

# 可用 --build-arg PIP_INDEX_URL=<mirror> 指向任意 PyPI 镜像。
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=180

COPY pyproject.toml setup.py README.md LICENSE ./
COPY src/ ./src/
RUN pip install --no-cache-dir --retries 5 .

ENV SPC_ENVIRONMENT=development \
    SPC_STATE_ROOT=/data/state \
    SPC_CACHE_ROOT=/data/cache \
    SPC_DATA_ROOT=/data/data
VOLUME ["/data", "/work"]
WORKDIR /work

ENTRYPOINT ["spc"]
CMD ["--help"]
