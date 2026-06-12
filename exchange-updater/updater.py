"""
환율 자동 갱신 — open.er-api.com → Redis (rate:KRW-<통화> + :prev)

매일 자정 1회 실행 (외부 API 가 일일 1회 갱신하므로 호출 주기도 일치).
- mcp-exchange 서버가 이 키들을 읽어 챗봇 환율 도구에 응답한다.
- gb-backend wallet-service 의 RealExchangeRateClient + /wallets/exchange-rates 도
  같은 키를 읽는다.

키 패턴 (mcp-exchange / wallet-service 와 SSOT 합의):
  rate:KRW-<통화>          → string decimal  (오늘 환율)
  rate:KRW-<통화>:prev      → string decimal  (어제 환율, 전일 대비 등락률 산정용)

TTL: 90000초 (25시간). 일일 갱신 + 1시간 여유로 다음 자정까지 살아있음.

지원 통화 7개: VND, PHP, USD, THB, IDR, CNY, JPY
"""
import logging
import os
import sys
from decimal import Decimal

import redis
import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("exchange-updater")

# 외부 환율 API — open.er-api.com (무료, 무가입)
EXCHANGE_API_URL = "https://open.er-api.com/v6/latest/KRW"

# 지원 통화 — mcp-exchange / wallet-service 와 합의된 SSOT
SUPPORTED_CURRENCIES = ["VND", "PHP", "USD", "THB", "IDR", "CNY", "JPY"]

# Redis 키 TTL — 일일 갱신 + 1시간 여유 (다음 자정까지 살아있도록)
TTL_SECONDS = 90000


def fetch_rates() -> dict[str, Decimal]:
    """open.er-api.com 호출 → 1 KRW 기준 환율 dict 반환.

    응답 형식:
        {"result":"success", "base_code":"KRW",
         "rates": {"USD": 0.00072, "VND": 18.5, ...}}

    rates[VND] = 18.5 의 의미: 1 KRW = 18.5 VND
    → mcp-exchange 의 `rate:KRW-VND = 18.5` 와 동일 의미.
    """
    logger.info("Fetching rates from %s", EXCHANGE_API_URL)
    resp = requests.get(EXCHANGE_API_URL, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if data.get("result") != "success":
        raise RuntimeError(f"Exchange API returned non-success: {data}")

    rates_raw = data.get("rates", {})
    rates: dict[str, Decimal] = {}
    for currency in SUPPORTED_CURRENCIES:
        if currency not in rates_raw:
            logger.warning("Currency %s missing in API response — skipping", currency)
            continue
        rates[currency] = Decimal(str(rates_raw[currency]))
    return rates


def get_redis_client() -> redis.Redis:
    """환경변수 기반 Redis 클라이언트 생성. mcp-exchange 와 동일 패턴.

    REDIS_SSL_ENABLED=true 시 TLS 활성화 — ElastiCache(stage/prod) 전송중 암호화 대응.
    SM sb/stage/redis/auth 의 tls 프로퍼티가 ExternalSecret 을 통해 이 변수로 주입된다.
    """
    ssl_enabled = os.environ.get("REDIS_SSL_ENABLED", "false").lower() == "true"
    return redis.Redis(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        password=os.environ.get("REDIS_PASSWORD") or None,
        db=int(os.environ.get("REDIS_DB", "0")),
        ssl=ssl_enabled,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )


def store_rates(client: redis.Redis, rates: dict[str, Decimal]) -> None:
    """
    매일 자정 호출 흐름:
      1. 기존 rate:KRW-<통화> 값(어제 환율) 을 rate:KRW-<통화>:prev 로 백업
      2. 새 값(오늘 환율) 을 rate:KRW-<통화> 에 저장 (TTL 25시간 갱신)

    첫 실행 시 prev 가 없으면 백업 단계 스킵 — 호출 측(API)에서 change_rate=0 처리.

    SETEX 들을 pipeline 으로 묶어 원자성·네트워크 비용 최소화.
    (MGET 은 결과를 다시 써야 해서 pipeline 밖에서 별도 호출.)
    """
    # 1) 모든 통화의 기존 값을 GET — pipeline 으로 한 번에
    keys = [f"rate:KRW-{c}" for c in rates.keys()]
    old_values = client.mget(keys)

    # 2) prev 백업 + 새 값 저장을 pipeline 으로 묶어 한 번에
    pipe = client.pipeline()
    for (currency, new_rate), old_value in zip(rates.items(), old_values):
        key = f"rate:KRW-{currency}"
        prev_key = f"{key}:prev"

        if old_value is not None:
            pipe.setex(prev_key, TTL_SECONDS, old_value)

        pipe.setex(key, TTL_SECONDS, str(new_rate))

    pipe.execute()

    for currency, new_rate in rates.items():
        logger.info("SET rate:KRW-%s = %s (TTL %ds)", currency, new_rate, TTL_SECONDS)


def main() -> int:
    try:
        rates = fetch_rates()
        if not rates:
            logger.error("No rates fetched; aborting")
            return 1

        client = get_redis_client()
        client.ping()  # 연결 검증
        store_rates(client, rates)
        logger.info("Done — %d currencies updated", len(rates))
        return 0
    except Exception as e:
        logger.error("Update failed: %s: %s", type(e).__name__, e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
