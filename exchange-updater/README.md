# exchange-updater

**매일 자정 1회** 외부 환율 API (`open.er-api.com`, 무료·무가입) 를 호출해 Redis 에 KRW 기준 환율을 저장.

> open.er-api.com 은 데이터를 일일 1회 갱신하므로, 호출 주기도 자정 1회로 맞춤. 매시간 갱신은 같은 값 반복이라 의미가 없고 등락률(change_rate) 도 항상 0 이 됨.

- **mcp-exchange** 서버가 이 키를 읽어 챗봇 환율 도구에 응답
- **gb-backend wallet-service** 의 `RealExchangeRateClient` + `/wallets/exchange-rates` API 도 같은 키를 읽음

---

## 키 패턴

| 키 | 값 | TTL |
|---|---|---|
| `rate:KRW-<통화>` | 오늘 환율 (string decimal, 1 KRW 기준) | 90000초 (25시간) |
| `rate:KRW-<통화>:prev` | 어제 환율 — 전일 대비 등락률 산정용 | 90000초 |

지원 통화 7개: `VND`, `PHP`, `USD`, `THB`, `IDR`, `CNY`, `JPY`

> **SSOT** : 키 패턴은 `gb-backend/docs/database.md` §7 + `gb-mcp-servers/mcp-exchange/server.py` 와 동일.

---

## 설치 (server01)

```bash
cd ~/projects
git clone https://github.com/Sangam-Beavers/gb-mcp-servers.git   # (없으면)
cd gb-mcp-servers/exchange-updater

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env   # REDIS_PASSWORD 등 환경에 맞게 수정
```

---

## 수동 테스트

```bash
source .venv/bin/activate
python updater.py
```

기대 출력:
```
... [INFO] Fetching rates from https://open.er-api.com/v6/latest/KRW
... [INFO] SET rate:KRW-VND = 18.5 (TTL 7200s)
... [INFO] SET rate:KRW-PHP = 0.04 (TTL 7200s)
... [INFO] SET rate:KRW-USD = 0.00072 (TTL 7200s)
...
... [INFO] Done — 7 currencies updated
```

Redis 직접 확인:
```bash
redis-cli -h 10.10.1.194 -a <비밀번호> KEYS "rate:KRW-*"
redis-cli -h 10.10.1.194 -a <비밀번호> GET "rate:KRW-VND"
```

2회차 부터 `rate:KRW-VND:prev` 키가 같이 보여야 정상 (등락률 산정용).

---

## crontab 등록

```bash
crontab -e
```

다음 한 줄 추가 (매일 자정 1회 실행):
```cron
0 0 * * * cd /home/ubuntu/projects/gb-mcp-servers/exchange-updater && /home/ubuntu/projects/gb-mcp-servers/exchange-updater/.venv/bin/python /home/ubuntu/projects/gb-mcp-servers/exchange-updater/updater.py >> /home/ubuntu/projects/gb-mcp-servers/exchange-updater/cron.log 2>&1
```

검증 — 다음 정각 (또는 cron 시간 조정) 까지 기다린 후:
```bash
tail -f ~/projects/gb-mcp-servers/exchange-updater/cron.log
```

---

## 등락률 (change_rate) 동작

- 첫 실행 → `prev` 키 없음 → API 측에서 `change_rate=0` 으로 처리
- 2일차부터 → `prev` 키 채워짐 → `(오늘 − 어제) / 어제 × 100` 으로 산정

자정 1회 갱신이므로 **전일 대비 등락률** 이 정확히 잡힘. open.er-api.com 의 일일 갱신 주기와 일치.

---

## 운영기 진입 시 후속 작업

- 송금팀 책임으로 이관 (현재는 PM 이 데모용 구현)
- K8s CronJob 으로 전환
- 외부 환율 API 다중화 (open.er-api.com 외 백업 소스 — 안정성 ↑)
- 시간 단위 더 잦은 갱신이 필요해지면 유료 API (exchangerate-api.com, fixer.io 등) 도입 + cron 주기 단축

---

*Sangam-Beavers | gb-mcp-servers | exchange-updater*
