# MCP2 커뮤니티 검색 서버 — 멀티스테이지 빌드 (mcp-exchange와 동일 패턴)

# ──────────────────────────────────────────────────────────────────────────────
# Stage 1: 의존성 빌드
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# pip 캐시 최적화: requirements만 먼저 복사
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ──────────────────────────────────────────────────────────────────────────────
# Stage 2: 런타임 (가벼움)
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

# 비특권 사용자 생성 (보안 권장)
RUN useradd -m -u 1000 mcp

WORKDIR /app

# 빌더 이미지에서 설치된 패키지만 복사
COPY --from=builder /root/.local /home/mcp/.local
ENV PATH=/home/mcp/.local/bin:$PATH

# 서버 코드 복사
COPY server.py .

# 소유권을 비특권 사용자에게
RUN chown -R mcp:mcp /app
USER mcp

# Streamable HTTP 기본 포트
EXPOSE 8000

# Healthcheck — TCP 연결만 확인
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(2); s.connect(('localhost', 8000)); s.close()" || exit 1

CMD ["python", "server.py"]
