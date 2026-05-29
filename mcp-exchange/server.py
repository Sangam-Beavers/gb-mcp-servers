"""
MCP1 — 환율 조회 서버 (FastMCP + Redis)

챗봇이 "월급 베트남 돈으로 얼마야?" 같은 환율 질문을 받으면 호출하는 MCP 서버.
송금팀이 운영하는 Redis에서 환율 값을 읽어 응답한다.

설계 정본: gb-backend/docs/document-analysis/ai-chatbot-mcp.md §9

키 패턴:  exchange:KRW:<통화>  → string decimal
예시:     exchange:KRW:VND     → "18.5"
"""

import logging
import os

import redis
from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mcp-exchange")

# ──────────────────────────────────────────────────────────────────────────────
# Redis 클라이언트
# ──────────────────────────────────────────────────────────────────────────────
# 환경변수 (Helm values 또는 docker-compose에서 주입):
#   REDIS_HOST     (기본 localhost)
#   REDIS_PORT     (기본 6379)
#   REDIS_PASSWORD (없으면 None)
#   REDIS_DB       (기본 0)
redis_client = redis.Redis(
    host=os.environ.get("REDIS_HOST", "localhost"),
    port=int(os.environ.get("REDIS_PORT", "6379")),
    password=os.environ.get("REDIS_PASSWORD") or None,
    db=int(os.environ.get("REDIS_DB", "0")),
    decode_responses=True,
    socket_timeout=5,
    socket_connect_timeout=5,
)

# 지원 통화 화이트리스트. Redis에 없는 통화는 즉시 거부해서 Redis 부하 줄임.
# 새 통화 추가 시 송금팀과 키 합의 후 여기 추가.
SUPPORTED_CURRENCIES = {"VND", "PHP", "USD", "THB", "IDR", "CNY", "JPY"}

# ──────────────────────────────────────────────────────────────────────────────
# MCP 서버
# ──────────────────────────────────────────────────────────────────────────────
mcp = FastMCP(
    "exchange-rate",
    instructions=(
        "원화(KRW) 금액을 다른 통화로 환산하는 환율 도구입니다. "
        "외국인 사용자가 한국에서 받는 임금·금액을 본국 통화로 환산할 때 사용하세요."
    ),
)


@mcp.tool()
def get_exchange_rate(amount_krw: float, target_currency: str) -> str:
    """원화(KRW) 금액을 다른 통화로 환산합니다.

    외국인 사용자가 한국에서 받는 임금이나 금액을 본국 통화로 환산할 때 사용합니다.
    환율 정보는 송금팀 Redis에서 실시간으로 가져옵니다.

    Args:
        amount_krw: 원화 금액 (예: 2000000)
        target_currency: 목표 통화 코드 (VND, PHP, USD, THB, IDR, CNY, JPY)

    Returns:
        환산 결과 문자열. 예: "2,000,000 KRW ≈ 37,000,000.00 VND (1 KRW = 18.5 VND)"
    """
    target = target_currency.upper().strip()

    # 1. 화이트리스트 검증 — 지원하지 않는 통화는 즉시 거부
    if target not in SUPPORTED_CURRENCIES:
        logger.warning("Unsupported currency requested: %s", target_currency)
        return (
            f"지원하지 않는 통화입니다: {target_currency}. "
            f"지원 통화: {', '.join(sorted(SUPPORTED_CURRENCIES))}"
        )

    # 2. Redis 조회
    key = f"exchange:KRW:{target}"
    try:
        rate_str = redis_client.get(key)
    except redis.RedisError as e:
        logger.error("Redis error on key=%s: %s", key, e)
        return "환율 조회 중 일시적 오류가 발생했습니다. 잠시 후 다시 시도해주세요."

    if rate_str is None:
        logger.warning("No exchange rate in Redis for key=%s", key)
        return f"환율 정보가 아직 등록되지 않았습니다: KRW → {target}"

    # 3. 값 파싱
    try:
        rate = float(rate_str)
    except (TypeError, ValueError):
        logger.error("Invalid rate value in Redis for key=%s: %r", key, rate_str)
        return "환율 데이터 형식 오류 — 운영팀에 문의해주세요."

    # 4. 환산 + 응답 조립
    converted = amount_krw * rate
    return (
        f"{amount_krw:,.0f} KRW ≈ {converted:,.2f} {target} "
        f"(1 KRW = {rate} {target})"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info(
        "Starting MCP exchange-rate server (transport=streamable-http, port=8000)"
    )
    logger.info(
        "Redis: host=%s port=%s db=%s",
        os.environ.get("REDIS_HOST", "localhost"),
        os.environ.get("REDIS_PORT", "6379"),
        os.environ.get("REDIS_DB", "0"),
    )
    mcp.run(transport="streamable-http")
