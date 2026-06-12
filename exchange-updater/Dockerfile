# exchange-updater — 환율 갱신 CronJob 이미지
# mcp-exchange 와 같은 멀티스테이지 패턴.
# 서버가 아닌 일회성 스크립트라 EXPOSE / HEALTHCHECK 없음.
#
# 빌드 컨텍스트: gb-mcp-servers 레포 루트 (wallet Dockerfile 과 동일 규칙)
#   kaniko: --context `pwd` --dockerfile exchange-updater/Dockerfile

# ──────────────────────────────────────────────────────────────────────────────
# Stage 1: 의존성 빌드
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

COPY exchange-updater/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ──────────────────────────────────────────────────────────────────────────────
# Stage 2: 런타임 (가벼움)
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

RUN useradd -m -u 1000 updater

WORKDIR /app

COPY --from=builder /root/.local /home/updater/.local
ENV PATH=/home/updater/.local/bin:$PATH

COPY exchange-updater/updater.py .

RUN chown -R updater:updater /app
USER updater

# CronJob: 실행 완료 후 종료 → EXPOSE / HEALTHCHECK 불필요
CMD ["python", "updater.py"]
