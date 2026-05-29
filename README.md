# gb-mcp-servers

> Global Bridge 챗봇용 MCP(Model Context Protocol) 서버 모음.
> 외국인 노동자 계약서 분석 챗봇이 외부 데이터(환율·커뮤니티)를 가져올 때 호출하는 어댑터.

---

## 구성

| 서버 | 도구 | 데이터 출처 | 상태 |
| --- | --- | --- | --- |
| `mcp-exchange` | `get_exchange_rate` | 송금팀 Redis (10.10.1.194) | 🚧 개발 중 |
| `mcp-community` | `search_community_posts` | 커뮤팀 posts DB (MySQL) | 📋 계획됨 |

법령 검색은 MCP 아님 — Bedrock Knowledge Bases로 분석 파이프라인과 공유 (`ai-chatbot-mcp.md` §2).

---

## 폴더 구조

```
gb-mcp-servers/
├── mcp-exchange/        MCP1 환율 서버 (FastMCP + Redis)
├── mcp-community/       MCP2 커뮤니티 서버 (FastMCP + MySQL)
├── helm/                K8s 배포 차트 (두 서버 공용)
└── docker-compose.yml   로컬 통합 테스트 (두 서버 동시 띄움)
```

---

## 로컬 실행

```bash
# 의존성 설치 (각 서버 폴더에서)
cd mcp-exchange
python -m venv .venv && source .venv/Scripts/activate  # Windows
pip install -r requirements.txt

# Redis 접속 정보 환경변수
export REDIS_HOST=10.10.1.194
export REDIS_PORT=6379
export REDIS_PASSWORD=...

# 서버 실행 (Streamable HTTP, port 8000)
python server.py
```

---

## 배포

| 환경 | 위치 | 설치 |
| --- | --- | --- |
| dev | 온프렘 K8s | `helm install mcp-dev helm/ -f helm/values-dev.yaml` |
| stage | AWS EKS | `helm install mcp-stage helm/ -f helm/values-stage.yaml` |
| prod | AWS EKS | `helm install mcp-prod helm/ -f helm/values-prod.yaml` |

`replicas=2 + PodDisruptionBudget(minAvailable=1)` — 무중단 보장.

---

## 관련 문서

- `ai-chatbot-mcp.md` — 챗봇 + MCP 정본 (gb-backend `docs/document-analysis/`)
- `AI-WORK-SPLIT.md` — AI 파트 작업 분담

---

*Sangam-Beavers / Global Bridge*
