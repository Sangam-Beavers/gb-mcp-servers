"""
MCP2 — 커뮤니티 게시글 검색 서버 (FastMCP + MySQL)

챗봇이 "비슷한 경험 한 사람?" 같은 질문을 받으면 호출하는 MCP 서버.
community_db.posts + comments를 LIKE 검색해 관련 글의 제목·본문·댓글을 반환한다.

설계 정본: gb-backend/docs/document-analysis/ai-chatbot-mcp.md §9
DB 스키마: gb-backend/docs/database.md §4 posts/comments SSOT

쿼리 전략 (2단계):
  1. posts.title / posts.content / comments.content LIKE '%query%' → 매칭되는 post.id 후보 N개
  2. 그 post들의 본문 + 매칭 무관하게 모든 댓글을 LEFT JOIN으로 한 번에 가져옴
이렇게 두 단계로 나누면 LIMIT가 글 단위로 정확히 적용되고, 결과 글은 댓글 풀세트를 함께 반환할 수 있다.

LIKE는 한국어 분절을 못 잡지만 데모 데이터(글 10·댓글 20)에서 충분히 매칭됨.
운영 가면 ngram 인덱스 + MATCH AGAINST 또는 OpenSearch 전환 검토.
"""

import logging
import os

import mysql.connector
from mcp.server.fastmcp import FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mcp-community")

# ──────────────────────────────────────────────────────────────────────────────
# MySQL 접속 정보
# ──────────────────────────────────────────────────────────────────────────────
# 환경변수 (Helm values 또는 docker-compose에서 주입):
#   COMMUNITY_DB_HOST     (기본 localhost)
#   COMMUNITY_DB_PORT     (기본 3306)
#   COMMUNITY_DB_USER     (기본 community_user)
#   COMMUNITY_DB_PASSWORD (필수)
#   COMMUNITY_DB_NAME     (기본 community_db)
#
# TODO(운영 전환): 읽기 전용 mcp_reader 계정 발급 후 USER/PASSWORD 환경변수만 교체.
#                 MCP는 절대 INSERT/UPDATE 하지 않으므로 SELECT 권한만 부여하면 충분.
DB_HOST = os.environ.get("COMMUNITY_DB_HOST", "localhost")
DB_PORT = int(os.environ.get("COMMUNITY_DB_PORT", "3306"))
DB_USER = os.environ.get("COMMUNITY_DB_USER", "community_user")
DB_PASSWORD = os.environ.get("COMMUNITY_DB_PASSWORD", "")
DB_NAME = os.environ.get("COMMUNITY_DB_NAME", "community_db")

# 가드값
MAX_LIMIT = 10               # LLM이 너무 많이 요청해도 잘라냄 (응답 토큰 폭주 방지)
MAX_QUERY_LEN = 200          # 쿼리 길이 상한 (DoS 방지)
MAX_TOKENS = 10              # query 공백 split 후 토큰 상한 (DoS + WHERE 절 폭발 방지)
MIN_TOKEN_LEN = 2            # 1글자 토큰은 너무 광범위하게 매칭돼서 제외 (한국어 조사 등)
MAX_COMMENTS_PER_POST = 5    # 글당 노출 댓글 수 상한
CONTENT_PREVIEW_LEN = 300    # 본문 미리보기 자르기

# ──────────────────────────────────────────────────────────────────────────────
# MCP 서버
# ──────────────────────────────────────────────────────────────────────────────
# ⚠ host/port는 생성자에 직접 넘겨야 한다. FastMCP.__init__이 host="127.0.0.1"을 Settings에
#   명시적으로 전달하는데, pydantic-settings 우선순위가 init 인자 > 환경변수라 FASTMCP_HOST env로는
#   덮어쓸 수 없다(무시됨). K8s에서 0.0.0.0 바인딩이 안 되면 Service/probe가 못 붙어 pod가 0/1로 뜬다.
#   또한 host=0.0.0.0이면 localhost용 DNS rebinding 자동보호도 비활성화되어 Service DNS 호출이 통과된다.
mcp = FastMCP(
    "community-posts",
    instructions=(
        "외국인 노동자 커뮤니티에서 사용자 질문과 비슷한 경험을 다룬 게시글과 "
        "댓글을 검색하는 도구입니다. 사용자의 고민(임금 체불, 비자, 계약서, 초과근무 등)에 "
        "공감과 실전 조언을 제공해야 할 때 호출하세요."
    ),
    host=os.environ.get("FASTMCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("FASTMCP_PORT", "8000")),
    # 멀티 레플리카(replicas=2) + NLB 분산 환경: 세션을 서버에 들지 않는 stateless HTTP로
    # 동작시켜야 어느 Pod이 받아도 처리된다. stateful이면 POST(세션 생성)와 GET(스트림)이
    # 서로 다른 Pod로 가 404로 깨진다(세션 affinity 부재).
    stateless_http=True,
)


def _get_connection():
    """매 호출마다 새 connection (FastMCP는 stateless 함수 + 데모 트래픽이 낮음)."""
    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        connection_timeout=5,
    )


@mcp.tool()
def search_community_posts(query: str, limit: int = 3) -> str:
    """커뮤니티에서 사용자 질문과 비슷한 경험을 한 다른 사용자의 게시글과 댓글을 검색합니다.

    외국인 노동자 커뮤니티에서 비슷한 고민(임금 미달·체불, 비자, 초과근무, 계약서 등)을
    겪은 사용자가 있는지 찾고 싶을 때 사용하세요. 게시글 제목·본문뿐 아니라 댓글까지
    함께 검색해 실제 사례와 다른 사용자들의 조언을 한꺼번에 반환합니다.

    검색 전략:
        - query를 공백 기준으로 split → 각 토큰별 OR LIKE 매칭
        - 한 토큰이라도 title/content/comments 어디든 매치되면 그 글 포함
        - 1글자 토큰(한국어 조사 등)은 제외, 최대 MAX_TOKENS개 토큰까지
        - 짧은 키워드("최저임금")든 긴 자연어("최저임금 미달 임금 못 받음")든 안정 매칭

    Args:
        query: 검색할 키워드. 단일 단어 또는 공백 구분 다단어 가능.
               예: "최저임금", "주 60시간", "임금 체불 신고", "E-9 비자 사업장 변경"
        limit: 반환할 게시글 수 (기본 3, 최대 10). 글 1개당 본문 + 댓글 최대 5개 포함.

    Returns:
        매칭된 게시글의 제목·카테고리·본문 미리보기·댓글을 정리한 자연어 텍스트.
        매칭이 없으면 그 사실을 안내하는 문자열.
    """
    q = (query or "").strip()
    if not q:
        return "검색어가 비어있습니다."
    if len(q) > MAX_QUERY_LEN:
        return f"검색어가 너무 깁니다 (최대 {MAX_QUERY_LEN}자)."

    # 공백 기준 split + MIN_TOKEN_LEN 미만 토큰 필터 + MAX_TOKENS 가드
    tokens = [t for t in q.split() if len(t) >= MIN_TOKEN_LEN][:MAX_TOKENS]
    if not tokens:
        return (
            f'"{q}"에서 유효한 검색 키워드를 찾지 못했습니다. '
            f"({MIN_TOKEN_LEN}자 이상의 단어로 검색해주세요)"
        )

    safe_limit = max(1, min(int(limit), MAX_LIMIT))

    # 토큰별 OR 조건 동적 생성:
    #   ((p.title LIKE %s OR p.content LIKE %s OR c.content LIKE %s)
    #    OR (p.title LIKE %s OR p.content LIKE %s OR c.content LIKE %s)
    #    OR ...)
    or_blocks = " OR ".join(
        ["(p.title LIKE %s OR p.content LIKE %s OR c.content LIKE %s)"
         for _ in tokens]
    )
    params: list = []
    for t in tokens:
        like = f"%{t}%"
        params.extend([like, like, like])
    params.append(safe_limit)

    try:
        conn = _get_connection()
        cursor = conn.cursor(dictionary=True)

        # 1단계 — 매칭되는 post id 후보 추출 (글 단위 LIMIT 적용, 토큰별 OR)
        cursor.execute(
            f"""
            SELECT DISTINCT p.id
            FROM posts p
            LEFT JOIN comments c
                   ON c.post_id = p.id AND c.deleted_at IS NULL
            WHERE p.deleted_at IS NULL
              AND ({or_blocks})
            ORDER BY p.id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        post_ids = [row["id"] for row in cursor.fetchall()]

        if not post_ids:
            cursor.close()
            conn.close()
            return f'"{q}"에 대한 관련 게시글이 없습니다.'

        # 2단계 — 후보 글들의 본문 + 댓글 전체 (LIMIT 무관, 글 단위로 가져옴)
        placeholders = ",".join(["%s"] * len(post_ids))
        cursor.execute(
            f"""
            SELECT p.id          AS post_id,
                   p.title       AS title,
                   p.content     AS content,
                   p.category    AS category,
                   p.comment_count AS comment_count,
                   c.content     AS comment_content
            FROM posts p
            LEFT JOIN comments c
                   ON c.post_id = p.id AND c.deleted_at IS NULL
            WHERE p.id IN ({placeholders}) AND p.deleted_at IS NULL
            ORDER BY p.id DESC, c.id ASC
            """,
            tuple(post_ids),
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

    except mysql.connector.Error as e:
        logger.error("MySQL error: %s", e)
        return "커뮤니티 검색 중 일시적 오류가 발생했습니다. 잠시 후 다시 시도해주세요."

    # 글 단위로 그룹핑
    posts: dict[int, dict] = {}
    for row in rows:
        pid = row["post_id"]
        if pid not in posts:
            posts[pid] = {
                "title": row["title"],
                "content": row["content"],
                "category": row["category"],
                "comment_count": row["comment_count"],
                "comments": [],
            }
        if row["comment_content"]:
            if len(posts[pid]["comments"]) < MAX_COMMENTS_PER_POST:
                posts[pid]["comments"].append(row["comment_content"])

    # 출력 포맷 — LLM이 자연스럽게 인용하도록 마크다운 헤딩 + 댓글 bullet
    out: list[str] = [
        f'커뮤니티에서 "{q}"와 관련된 게시글 {len(posts)}개를 찾았습니다.\n'
    ]
    for post in posts.values():
        content_preview = post["content"][:CONTENT_PREVIEW_LEN]
        if len(post["content"]) > CONTENT_PREVIEW_LEN:
            content_preview += "..."

        out.append(f"### [{post['category']}] {post['title']}")
        out.append(f"본문: {content_preview}")
        if post["comments"]:
            out.append(f"댓글({post['comment_count']}개 중 일부):")
            for cmt in post["comments"]:
                out.append(f"- {cmt}")
        else:
            out.append("(댓글 없음)")
        out.append("")  # 글 사이 빈 줄

    return "\n".join(out).rstrip()


# ──────────────────────────────────────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info(
        "Starting MCP community-posts server (transport=streamable-http, port=8000)"
    )
    logger.info("MySQL: %s@%s:%s/%s", DB_USER, DB_HOST, DB_PORT, DB_NAME)
    mcp.run(transport="streamable-http")
