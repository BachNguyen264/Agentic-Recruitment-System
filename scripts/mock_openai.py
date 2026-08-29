"""mock_openai — API OpenAI GIẢ chạy tại chỗ, để đo HỆ THỐNG chứ KHÔNG đo LLM.

VÌ SAO CÓ FILE NÀY. Audit đồng thời (9 chiều) chỉ ra nút thắt thật không nằm ở OpenAI mà ở
**một ThreadPoolExecutor mặc định DÙNG CHUNG** của asyncio (rộng `min(32, cpu+4)`): parser gọi
OpenAI ĐỒNG BỘ (`parser.py` → `asyncio.to_thread(parse_cv, ...)`, ~9.4s/CV), R2 save/get
(`services/storage/r2.py`), gửi thư Resend (`services/email_service.py`) và ruột AsyncPostgresSaver
đều mượn ĐÚNG cái pool đó. Ranker tuy lâu hơn (~24.7s) nhưng đi `ainvoke` nên KHÔNG tốn luồng nào.
Cùng lúc, đường NHẬN CV giữ 1 trong 15 connection DB suốt lượt upload R2 ⇒ hàng đợi ở thread pool
biến thành **cạn pool DB**. Muốn nhìn thấy chuỗi nhân quả đó thì phải chạy ĐÚNG đường code thật.

`ENABLE_LLM=false` KHÔNG dùng để đo được: nó stub CẢ parser lẫn ranker ⇒ xoá sạch đúng cái khoảng
thời gian chiếm luồng cần quan sát. Vì vậy ta không TẮT LLM mà ĐỔI ĐÍCH của nó:

    OPENAI_API_BASE=http://127.0.0.1:9099/v1

`ChatOpenAI` lẫn `OpenAIEmbeddings` đều đọc biến này (langchain_openai) ⇒ KHÔNG sửa một dòng code
ứng dụng nào. Đường đi giữ nguyên: structured output, thread pool, retry của openai-client.

CẢNH BÁO — thứ đo qua mock KHÔNG phải LLM:
  - Mọi con số lấy qua đây là số đo của **hệ thống QUANH LLM** (thread pool, pool DB, RAM, hàng đợi
    BackgroundTasks), KHÔNG phải chất lượng/độ trễ thật của OpenAI. Độ trễ ở đây là hằng số do BẠN
    đặt bằng CLI — nó chỉ giả lập "một lượt gọi tốn ngần này giây", không giả lập được p99 của
    provider, cắt token, cold start hay quota thật.
  - Dữ liệu trả về là **BỊA** (CV giả, điểm cố định). Trỏ hệ thống THẬT vào đây rồi chạy demo là ghi
    hồ sơ bịa vào DB và có thể GỬI EMAIL THẬT dựa trên điểm bịa (gate auto-mời/auto-từ-chối) —
    xem `--confirm`.
  - Client vẫn gửi **OPENAI_API_KEY THẬT** tới đây (nó đâu biết mình đang nói chuyện với mock). Đó là
    lý do mặc định chỉ nghe trên loopback; ra ngoài mạng phải `--allow-remote` có chủ đích.

Chạy:
    uv run --directory apps/backend python ../../scripts/mock_openai.py --confirm
    # rồi ở cửa sổ khác, trỏ backend vào mock:
    OPENAI_API_BASE=http://127.0.0.1:9099/v1 make dev-backend
    # rồi bắn tải:
    uv run --directory apps/backend python ../../scripts/loadtest_apply.py --job-id 1 --total 60 --confirm

Ctrl-C để dừng: lúc đó mock in **đỉnh số request đồng thời TÁCH THEO MODEL**. Con số cần đọc là đỉnh
của RIÊNG model parser — chỉ parser đi `asyncio.to_thread` nên mỗi lượt parser đang bay = một luồng
của thread pool; nó chạm `min(32, cpu+4)` thì chính là nút thắt đang tìm. Đỉnh GỘP có cả ranker và
embedding (chạy trên event loop, không tốn luồng) nên KHÔNG dùng cho lập luận đó.
"""

from __future__ import annotations

import argparse
import array
import base64
import json
import os
import random
import re
import sys
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

# ── Hằng số nội dung giả ─────────────────────────────────────────────────────
# Điểm ranker CỐ ĐỊNH cho MỌI tiêu chí. Chọn 78 chứ không phải số bất kỳ, vì đường "happy path"
# của ranker.py đòi ba điều cùng lúc (xem `_flags_and_confidence`):
#   - >= SCORE_PASS_THRESHOLD (mặc định 60) ⇒ không `require_human_review`;
#   - cách ngưỡng > SCORE_NEAR_BAND (mặc định 10) ⇒ không cờ `near_threshold`;
#   - mọi tiêu chí CÙNG điểm ⇒ trung bình có trọng số == `overall_score` bất kể trọng số JD là gì
#     ⇒ không dính log "điểm tính lại lệch LLM" (`_OVERALL_DIVERGE`).
# Đổi SCORE_PASS_THRESHOLD trong .env thì nhớ ngó lại số này.
_RANK_SCORE = 78.0

# Rubric dự phòng khi KHÔNG bóc được rubric từ prompt (JD chưa có rubric). Trọng số phải > 0, nếu
# không `_weighted_overall` trả None và ranker rơi về điểm LLM thô.
_FALLBACK_RUBRIC: list[tuple[str, float]] = [
    ("Kinh nghiệm liên quan", 40.0),
    ("Kỹ năng chuyên môn", 40.0),
    ("Học vấn", 20.0),
]

# Bóc rubric ra khỏi prompt của ranker. `ranker._format_rubric` sinh đúng dạng
# "- {criterion} (trọng số {weight})" nên regex này bám vào ĐỊNH DẠNG THẬT, không phải đoán.
_RUBRIC_LINE = re.compile(r"^-\s*(.+?)\s*\(trọng số\s*([0-9]+(?:\.[0-9]+)?)\)\s*$", re.MULTILINE)
_RUBRIC_HEAD = "===== RUBRIC"
_RUBRIC_TAIL = "===== CV ỨNG VIÊN"

# Vector giả CỐ Ý gần trùng nhau (nhiễu nhỏ quanh một vector nền) ⇒ cosine CV↔JD ≈ 0.99. Nếu sinh
# vector NGẪU NHIÊN độc lập thì trong không gian 1536 chiều chúng gần như trực giao (cosine ≈ 0)
# ⇒ ranker gắn `weak_match` + `score_signal_mismatch` cho MỌI hồ sơ ⇒ cả đợt tải rơi vào
# human_review và ta không còn đo được nhánh tự động. Nhiễu vẫn giữ để mỗi vector một khác.
_EMBED_NOISE = 0.05

# HÀNG ĐỢI LẮNG NGHE (listen backlog). `socketserver.TCPServer.request_queue_size` mặc định là **5**
# — đủ cho một máy chủ đồ chơi, THẢM HOẠ cho phép đo này. Đo thật trên máy Windows: 8 kết nối ập
# vào cùng lúc đã có 1 lượt phải phát lại SYN (connect 518ms); 32 lượt ⇒ 7 lượt CHẾT vì hết hạn
# 60s; 64 lượt ⇒ chỉ 25 lượt sống. Nghĩa là mock CHÍNH NÓ thành nút thắt và đợt tải sẽ ghi lại
# "backend chậm/timeout" trong khi backend còn chưa được chạm tới. Một CV = 1 kết nối parser mới +
# 1 kết nối ranker mới (`_build_parser_llm`/`build_ranker_llm` dựng ChatOpenAI MỚI mỗi lượt ⇒
# httpx client mới ⇒ connection mới), nên `--total 60` sinh ra hàng chục lượt connect đồng thời.
_LISTEN_BACKLOG = 512


class MockConfig:
    """Tham số vận hành của mock — toàn bộ đến từ CLI, KHÔNG hardcode trong nghiệp vụ."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.delays: dict[str, float] = {
            args.parser_model: args.parser_delay,
            args.ranker_model: args.ranker_delay,
            args.embed_model: args.embed_delay,
        }
        self.default_delay: float = args.default_delay
        self.jitter: float = args.jitter
        self.failure_rate: float = args.failure_rate
        self.dim: int = args.dim
        # Giữ tên model parser để báo cáo tách được ĐỈNH của riêng nó — xem `print_summary`.
        self.parser_model: str = args.parser_model


class MockStats:
    """Bộ đếm dùng chung giữa các luồng.

    Số đo QUAN TRỌNG NHẤT của file này là `max_in_flight_by_model[parser_model]` — đỉnh đồng thời
    của RIÊNG parser. `max_in_flight` (gộp mọi model) chỉ để đối chiếu, KHÔNG dùng cho lập luận về
    bề rộng thread pool: ranker/embedding nằm trong đó mà không tốn luồng nào.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.started = time.perf_counter()
        self.in_flight = 0
        self.max_in_flight = 0
        self.total = 0
        self.throttled = 0
        self.by_model: Counter[str] = Counter()
        # Đỉnh TÁCH THEO MODEL. Bắt buộc phải có: `max_in_flight` gộp chung parser (gọi ĐỒNG BỘ ⇒
        # chiếm một luồng của thread pool) với ranker/embedding (`ainvoke`/`aembed_query` ⇒ chạy
        # thẳng trên event loop, KHÔNG tốn luồng nào). Lấy con số gộp đem so với `min(32, cpu+4)`
        # là kết luận sai về bão hoà thread pool — đỉnh 20 có thể là 12 parser + 8 ranker.
        self.in_flight_by_model: Counter[str] = Counter()
        self.max_in_flight_by_model: Counter[str] = Counter()
        # Mốc request ĐẦU và CUỐI: mẫu số của "lượt/giây" phải là khoảng CÓ TẢI, không phải tuổi
        # tiến trình. Mock thường được bật trước rồi ngồi không vài phút chờ backend + loadtest;
        # chia cho tuổi tiến trình ra một con số thấp giả, và nó rất dễ bị chép thẳng vào báo cáo.
        self.first_at: float | None = None
        self.last_at: float = 0.0
        self.seq = 0

    def enter(self, model: str) -> tuple[int, int]:
        """Ghi nhận một request BẮT ĐẦU. Trả (số thứ tự, số đang bay sau khi cộng)."""
        with self.lock:
            self.seq += 1
            self.total += 1
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            self.by_model[model] += 1
            self.in_flight_by_model[model] += 1
            self.max_in_flight_by_model[model] = max(
                self.max_in_flight_by_model[model], self.in_flight_by_model[model]
            )
            if self.first_at is None:
                self.first_at = time.perf_counter()
            return self.seq, self.in_flight

    def leave(self, model: str) -> None:
        with self.lock:
            self.in_flight -= 1
            self.in_flight_by_model[model] -= 1
            self.last_at = time.perf_counter()


# ── Nội dung giả cho từng schema ─────────────────────────────────────────────


def fake_parsed_cv(seq: int) -> dict[str, Any]:
    """Một CV Việt Nam nghe được, khác nhau chút một theo `seq` để phân biệt hàng trên dashboard.

    Đủ 5 trường lõi (`parser._confidence`: full_name / email|phone / skills / experiences /
    education) ⇒ confidence = 1.0 ⇒ không cờ nào. Đây là chủ đích: load test cần đi nhánh SẠCH.
    """
    return {
        "full_name": f"Nguyễn Văn Mock {seq:04d}",
        "email": f"mock+{seq:04d}@example.com",
        "phone": f"09{seq:08d}",
        "skills": ["Python", "FastAPI", "PostgreSQL", "SQLAlchemy", "Docker", "Redis"],
        "experiences": [
            {
                "company": "Công ty Cổ phần Công nghệ ABC",
                "title": "Backend Engineer",
                "duration": "2022–2025",
                "summary": "Xây REST API, tối ưu truy vấn Postgres, triển khai Docker.",
            },
            {
                "company": "Công ty TNHH XYZ",
                "title": "Thực tập sinh Backend",
                "duration": "2021–2022",
                "summary": "Viết script ETL, hỗ trợ đội vận hành dữ liệu.",
            },
        ],
        "education": [
            {
                "school": "Đại học Bách Khoa",
                "degree": "Kỹ sư",
                "field": "Kỹ thuật Phần mềm",
                "year": "2021",
            }
        ],
        "total_years_experience": 3.5,
        "professional_summary": "Backend Engineer 3 năm kinh nghiệm Python/FastAPI, thiên về hệ thống chịu tải.",
        "certificates": [{"name": "TOEIC", "detail": "870/990", "year": "2023"}],
        "languages": [{"name": "Tiếng Anh", "proficiency": "Professional working"}],
        "awards": ["Giải Ba Olympic Tin học sinh viên cấp trường"],
        "other": [{"label": "Sở thích", "content": "Chạy bộ, đọc sách kỹ thuật."}],
    }


def rubric_from_prompt(prompt: str) -> list[tuple[str, float]]:
    """Bóc (tên tiêu chí, trọng số) ra khỏi prompt ranker.

    Mock KHÔNG truy vấn DB nên không biết rubric của JD — nhưng prompt thì CÓ CHỞ rubric theo
    (`ranker._build_prompt`). Echo lại đúng bộ tiêu chí đó khiến `_reconcile_criteria` ghép 1-1,
    không log "số tiêu chí LLM != rubric JD", và điểm tổng tính lại khớp tuyệt đối. Bóc hụt cũng
    KHÔNG sao — ranker ghép theo min rồi vẫn chạy tiếp (xem `_FALLBACK_RUBRIC`).
    """
    head = prompt.find(_RUBRIC_HEAD)
    if head < 0:
        return []
    tail = prompt.find(_RUBRIC_TAIL, head)
    block = prompt[head : tail if tail > head else len(prompt)]
    return [(m.group(1), float(m.group(2))) for m in _RUBRIC_LINE.finditer(block)]


def fake_rank_result(prompt: str) -> dict[str, Any]:
    """RankResult "sạch": mọi tiêu chí cùng `_RANK_SCORE` ⇒ điểm tổng bằng đúng số đó."""
    rubric = rubric_from_prompt(prompt) or _FALLBACK_RUBRIC
    return {
        "overall_score": _RANK_SCORE,
        "criteria": [
            {
                "criterion": name,
                "weight": weight,
                "score": _RANK_SCORE,
                "reasoning": "[MOCK] Điểm cố định do máy chủ giả sinh — KHÔNG phải đánh giá thật.",
            }
            for name, weight in rubric
        ],
        "summary": "[MOCK] Hồ sơ giả do mock_openai sinh ra để đo tải. Không dùng cho quyết định thật.",
    }


def _deref(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    if not isinstance(ref, str):
        return node
    resolved = defs.get(ref.rsplit("/", 1)[-1])
    return resolved if isinstance(resolved, dict) else {}


def minimal_from_schema(node: Any, defs: dict[str, Any], depth: int = 0) -> Any:
    """Dựng một instance TỐI THIỂU hợp lệ từ JSON Schema (đệ quy, hiểu `$defs`/`$ref`).

    Đây là lưới chống MỤC RỮA: khi ai đó thêm lượt gọi structured-output thứ ba (vd suggester rubric
    của JD-3), mock vẫn trả được thứ pydantic validate qua thay vì 500 và làm hỏng cả đợt đo. Không
    cố "đẹp" — chỉ cần ĐÚNG KIỂU và đủ trường `required`.
    """
    if depth > 12:  # schema tự tham chiếu — dừng, tránh đệ quy vô hạn.
        return None
    if not isinstance(node, dict):
        return None
    node = _deref(node, defs)

    for key in ("anyOf", "oneOf", "allOf"):
        branches = node.get(key)
        if isinstance(branches, list) and branches:
            # strict mode gói trường tuỳ chọn thành anyOf[T, null]. Lấy nhánh KHÁC null để payload
            # có dữ liệu thật, chứ không phải một cây toàn None.
            pick = next(
                (b for b in branches if _deref(b, defs).get("type") != "null"), branches[0]
            )
            return minimal_from_schema(pick, defs, depth + 1)

    enum = node.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]

    kind = node.get("type")
    if isinstance(kind, list):  # ["string", "null"] — lấy kiểu có dữ liệu.
        kind = next((k for k in kind if k != "null"), "null")

    if kind == "object":
        props = node.get("properties") or {}
        required = node.get("required") or list(props)
        return {k: minimal_from_schema(props.get(k, {}), defs, depth + 1) for k in required}
    if kind == "array":
        item = node.get("items")
        return [minimal_from_schema(item, defs, depth + 1)] if isinstance(item, dict) else []
    if kind == "string":
        return "[MOCK]"
    if kind == "integer":
        return 0
    if kind == "number":
        return 0.0
    if kind == "boolean":
        return False
    return None


# ── Đọc request ──────────────────────────────────────────────────────────────


def prompt_text(payload: dict[str, Any]) -> str:
    """Ghép nội dung mọi message thành một chuỗi (content có thể là str HOẶC list part)."""
    parts: list[str] = []
    for msg in payload.get("messages") or []:
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(p.get("text", "") for p in content if isinstance(p, dict))
    return "\n".join(parts)


def schema_of(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """(tên schema, schema) từ `response_format.json_schema`. Không có → ("", {})."""
    rf = payload.get("response_format")
    if not isinstance(rf, dict):
        return "", {}
    js = rf.get("json_schema")
    if not isinstance(js, dict):
        return "", {}
    schema = js.get("schema")
    return str(js.get("name") or ""), schema if isinstance(schema, dict) else {}


def embedding_count(payload: dict[str, Any]) -> int:
    """Số vector phải trả = số phần tử `input`.

    `OpenAIEmbeddings` mặc định `check_embedding_ctx_length=True` ⇒ nó TOKEN HOÁ trước và gửi
    `input` là list[list[int]] chứ không phải list[str]. Phải phân biệt được list token của MỘT
    chuỗi (toàn int) với list NHIỀU chuỗi, nếu không sẽ trả 1536 vector cho một câu.
    """
    value = payload.get("input")
    if isinstance(value, list):
        if not value:
            return 1
        if all(isinstance(x, int) for x in value):
            return 1
        return len(value)
    return 1


# ── Sinh vector ──────────────────────────────────────────────────────────────


def encode_embedding(vector: list[float], encoding_format: str) -> Any:
    """Trả list[float] hoặc chuỗi base64 — TÔN TRỌNG thứ client hỏi.

    openai-client mặc định gửi `encoding_format="base64"` khi caller không nói gì (langchain không
    nói gì), rồi tự `base64.b64decode` + `array("f")`. Trả list[float] trong ca đó thì client giữ
    nguyên list — vẫn chạy — nhưng ta bám đúng giao thức để không lệ thuộc chi tiết nội bộ ấy.
    """
    if encoding_format != "base64":
        return vector
    buf = array.array("f", vector)
    if sys.byteorder != "little":  # wire format của OpenAI là float32 LITTLE-endian.
        buf.byteswap()
    return base64.b64encode(buf.tobytes()).decode("ascii")


class VectorFactory:
    """Sinh vector `dim` chiều gần song song nhau (xem `_EMBED_NOISE`), lặp lại được theo --seed."""

    def __init__(self, dim: int, seed: int) -> None:
        base_rng = random.Random(seed)
        self.dim = dim
        self.base = [base_rng.gauss(0.0, 1.0) for _ in range(dim)]

    def make(self, salt: int) -> list[float]:
        rng = random.Random(salt)
        return [b + _EMBED_NOISE * rng.gauss(0.0, 1.0) for b in self.base]


# ── HTTP ─────────────────────────────────────────────────────────────────────


def build_handler(
    cfg: MockConfig,
    stats: MockStats,
    vectors: VectorFactory,
    rng_lock: threading.Lock,
    rng: random.Random,
) -> type[BaseHTTPRequestHandler]:
    """Tạo handler đóng gói sẵn cấu hình (BaseHTTPRequestHandler khởi tạo MỚI mỗi request)."""

    def draw(fn) -> float:
        # random.Random KHÔNG hứa an toàn đa luồng; khoá lại để --seed còn nghĩa lý.
        with rng_lock:
            return fn()

    def delay_for(model: str) -> float:
        base = cfg.delays.get(model, cfg.default_delay)
        if cfg.jitter <= 0:
            return max(base, 0.0)
        factor = 1.0 + draw(lambda: rng.uniform(-cfg.jitter, cfg.jitter))
        return max(base * factor, 0.0)

    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.1 + Content-Length ⇒ keep-alive thật. Để HTTP/1.0 thì mỗi lượt gọi phải bắt tay
        # TCP lại, và ta sẽ đo nhầm chi phí kết nối thành chi phí hệ thống.
        protocol_version = "HTTP/1.1"
        server_version = "mock-openai"
        sys_version = ""
        timeout = 120  # connection keep-alive ngồi không quá lâu thì thả luồng ra.

        def log_message(self, fmt: str, *args: Any) -> None:
            """Tắt access log mặc định — file này tự in dòng log GIÀU thông tin hơn."""

        # -- tiện ích --------------------------------------------------------

        def _send_json(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, code: int, message: str, err_type: str, err_code: str | None) -> None:
            """Thân lỗi hình dạng OpenAI — client phải nhận ra được để retry/raise cho đúng lớp."""
            self._send_json(
                code,
                {"error": {"message": message, "type": err_type, "param": None, "code": err_code}},
            )

        def _read_body(self) -> dict[str, Any] | None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length > 0 else b""
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._error(400, f"Body không phải JSON hợp lệ: {exc}", "invalid_request_error", None)
                return None
            return payload if isinstance(payload, dict) else {}

        def _log(self, seq: int, in_flight: int, note: str) -> None:
            print(
                f"[t+{time.perf_counter() - stats.started:7.1f}s] #{seq:04d} {note}"
                f"  in-flight={in_flight} (đỉnh {stats.max_in_flight})",
                flush=True,
            )

        # -- định tuyến ------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802 — tên do BaseHTTPRequestHandler quy định
            self._not_found()

        def do_POST(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path.rstrip("/") or "/"
            if path == "/v1/chat/completions":
                self._chat()
            elif path == "/v1/embeddings":
                self._embeddings()
            else:
                self._not_found()

        def _not_found(self) -> None:
            self._error(
                404,
                f"Mock chỉ phục vụ POST /v1/chat/completions và POST /v1/embeddings (nhận {self.path!r}).",
                "invalid_request_error",
                "unknown_url",
            )

        # -- endpoint --------------------------------------------------------

        def _chat(self) -> None:
            payload = self._read_body()
            if payload is None:
                return
            model = str(payload.get("model") or "?")
            name, schema = schema_of(payload)
            seq, in_flight = stats.enter(model)
            try:
                # THROTTLE trả về NGAY, KHÔNG chờ hết delay — provider từ chối quota là thao tác rẻ,
                # và chính vì rẻ nên nó dội về nhanh rồi kích retry của openai-client (mặc định 2
                # lần). Ngủ trước rồi mới 429 sẽ giấu mất đúng hiệu ứng dồn toa đó.
                if cfg.failure_rate > 0 and draw(rng.random) < cfg.failure_rate:
                    with stats.lock:
                        stats.throttled += 1
                    self._log(seq, in_flight, f"chat model={model} → 429 THROTTLE (--failure-rate)")
                    self._error(
                        429,
                        "Rate limit reached for requests (mock_openai --failure-rate).",
                        "requests",
                        "rate_limit_exceeded",
                    )
                    return

                delay = delay_for(model)
                self._log(
                    seq, in_flight,
                    f"chat model={model} schema={name or '-'} delay={delay:.2f}s",
                )
                time.sleep(delay)

                if name == "ParsedCV":
                    content = fake_parsed_cv(seq)
                elif name == "RankResult":
                    content = fake_rank_result(prompt_text(payload))
                else:
                    content = minimal_from_schema(schema, schema.get("$defs") or {})

                text = json.dumps(content, ensure_ascii=False)
                prompt_tokens = max(len(prompt_text(payload)) // 4, 1)
                completion_tokens = max(len(text) // 4, 1)
                self._send_json(
                    200,
                    {
                        "id": f"chatcmpl-mock-{seq:06d}",
                        "object": "chat.completion",
                        "created": int(time.time()),
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                # structured output kiểu json_schema: payload nằm ở content dưới
                                # dạng CHUỖI JSON (không phải object) — langchain tự json.loads rồi
                                # validate bằng pydantic.
                                "message": {"role": "assistant", "content": text, "refusal": None},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": prompt_tokens + completion_tokens,
                        },
                    },
                )
            finally:
                stats.leave(model)

        def _embeddings(self) -> None:
            payload = self._read_body()
            if payload is None:
                return
            model = str(payload.get("model") or "?")
            fmt = str(payload.get("encoding_format") or "float")
            count = embedding_count(payload)
            seq, in_flight = stats.enter(model)
            try:
                delay = delay_for(model)
                self._log(
                    seq, in_flight,
                    f"embed model={model} n={count} fmt={fmt} delay={delay:.2f}s",
                )
                time.sleep(delay)
                tokens = max(count * 64, 1)
                self._send_json(
                    200,
                    {
                        "object": "list",
                        "model": model,
                        "data": [
                            {
                                "object": "embedding",
                                "index": i,
                                "embedding": encode_embedding(vectors.make(seq * 1000 + i), fmt),
                            }
                            for i in range(count)
                        ],
                        "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
                    },
                )
            finally:
                stats.leave(model)

    return Handler


# ── Báo cáo ──────────────────────────────────────────────────────────────────


def print_banner(args: argparse.Namespace) -> None:
    print("=" * 78)
    print(f"MOCK OPENAI — nghe tại http://{args.host}:{args.port}/v1")
    print("=" * 78)
    print("── ĐỘ TRỄ GIẢ LẬP " + "─" * 59)
    print(f"   {args.parser_model:<24} {args.parser_delay:6.2f}s   (parser — gọi ĐỒNG BỘ ⇒ chiếm 1 luồng)")
    print(f"   {args.ranker_model:<24} {args.ranker_delay:6.2f}s   (ranker — ainvoke ⇒ KHÔNG tốn luồng)")
    print(f"   {args.embed_model:<24} {args.embed_delay:6.2f}s   (embedding, {args.dim} chiều)")
    print(f"   {'(model lạ)':<24} {args.default_delay:6.2f}s   --default-delay")
    print(f"   jitter ±{args.jitter:.0%} · seed {args.seed} · --failure-rate {args.failure_rate:.2%} (429)")
    print()
    print("── CẢNH BÁO " + "─" * 65)
    print("   Mọi số đo qua mock này là số đo của HỆ THỐNG QUANH LLM (thread pool, pool DB, RAM,")
    print("   hàng đợi BackgroundTasks) — KHÔNG phải số đo của LLM. Độ trễ ở đây là hằng số bạn tự")
    print("   đặt; nó không có p99, không cold start, không cắt token, không quota thật.")
    print("   Dữ liệu trả về là BỊA. Đừng để prod trỏ vào đây.")
    print()
    print("   Trỏ backend vào mock:  OPENAI_API_BASE=http://" f"{args.host}:{args.port}/v1")
    print("   Ctrl-C để dừng và xem đỉnh số request đồng thời.")
    print("=" * 78, flush=True)


def print_summary(stats: MockStats, cfg: MockConfig) -> None:
    uptime = time.perf_counter() - stats.started
    # Mẫu số ĐÚNG = khoảng CÓ TẢI (request đầu → request cuối rời đi), KHÔNG phải tuổi tiến trình.
    # Mock hay được bật trước rồi ngồi không chờ backend/loadtest; chia cho tuổi tiến trình cho ra
    # một "lượt/giây" thấp giả — đúng loại số dễ bị chép vào báo cáo mà không ai kiểm lại.
    active = (stats.last_at - stats.first_at) if stats.first_at is not None else 0.0
    print()
    print("── TỔNG KẾT MOCK " + "─" * 60)
    print(f"   {stats.total} request · tiến trình sống {uptime:.1f}s · CÓ TẢI {active:.1f}s"
          + (f" ⇒ {stats.total / active:.2f} lượt/giây (tính trên khoảng CÓ TẢI)" if active > 0 else ""))
    for model, n in sorted(stats.by_model.items()):
        print(f"   {model:<26} {n:5d} lượt · đỉnh đồng thời {stats.max_in_flight_by_model[model]:4d}"
              f"   (delay {cfg.delays.get(model, cfg.default_delay):.2f}s)")
    if cfg.failure_rate > 0:
        print(f"   429 THROTTLE đã trả: {stats.throttled} (KHÔNG chờ delay ⇒ không tính vào đỉnh thật)")
    # Model LẠ = lần chạy này KHÔNG đo cái ta tưởng. Đổi RANKER_MODEL trong .env mà quên
    # `--ranker-model` thì 24.7s lặng lẽ thành `--default-delay` (1s) và toàn bộ hình dạng tải sai
    # — sai theo hướng LẠC QUAN. Dòng log mỗi lượt có in tên model, nhưng không ai đọc 60 dòng log;
    # phải nói thẳng ở tổng kết.
    unknown = sorted(m for m in stats.by_model if m not in cfg.delays)
    if unknown:
        print()
        print("   " + "!" * 72)
        print(f"   !!  MODEL LẠ ĐÃ RƠI VỀ --default-delay ({cfg.default_delay:.2f}s): {', '.join(unknown)}")
        print("   !!  .env đang dùng tên model KHÁC cờ CLI ⇒ độ trễ giả lập SAI ⇒ số đo lần chạy này")
        print("   !!  KHÔNG dùng được. Đặt --parser-model/--ranker-model/--embed-model cho khớp .env.")
        print("   " + "!" * 72)
    print()
    pool_width = min(32, (os.cpu_count() or 1) + 4)
    parser_peak = stats.max_in_flight_by_model[cfg.parser_model]
    print(f"   ĐỈNH ĐỒNG THỜI CỦA RIÊNG PARSER ({cfg.parser_model}): {parser_peak}")
    print(f"   ĐỈNH GỘP MỌI MODEL: {stats.max_in_flight}  ← KHÔNG dùng số này cho lập luận thread pool")
    print("   Đọc thế nào: CHỈ parser đi `asyncio.to_thread` nên MỖI lượt parser đang bay = MỘT luồng")
    print("   của thread pool mặc định. Ranker (`ainvoke`) và embedding (`aembed_query`) chạy thẳng")
    print("   trên event loop, KHÔNG tốn luồng — chúng nằm trong ĐỈNH GỘP, nên lấy đỉnh gộp đem so")
    print(f"   với min(32, cpu+4) (máy NÀY: {pool_width} — phải lấy số của máy chạy BACKEND) là kết")
    print("   luận SAI về bão hoà. Chỉ khi ĐỈNH RIÊNG PARSER chạm trần đó thì pool mới thật sự bão")
    print("   hoà và phần tải còn lại đang XẾP HÀNG ở client chứ không phải ở đây.")
    print()
    print("   NHẮC LẠI: đây là số đo của hệ thống quanh LLM, không phải của LLM.")
    print("=" * 78, flush=True)


# ── main ─────────────────────────────────────────────────────────────────────


def _force_utf8_output() -> None:
    """Ép stdout/stderr về UTF-8 TRƯỚC khi in bất cứ thứ gì.

    Trên Windows, `sys.stdout` chỉ là UTF-8 khi nó nối thẳng vào console. Hễ bị CHUYỂN HƯỚNG —
    `> mock.log`, `| tee`, hay chạy qua subprocess (tức là ĐÚNG cách một đợt đo tải khởi chạy nó) —
    Python rơi về codec locale (cp1252 ở máy này) và mọi dòng tiếng Việt ném `UnicodeEncodeError`.
    Đo thật: chạy `mock_openai.py --confirm | head` thì nó CHẾT ngay ở dòng banner đầu tiên, TRƯỚC
    khi kịp bind cổng — nhìn hệt như "mock không lên" mà không có lời giải thích nào.
    `errors="replace"` là lưới cuối: thà một ký tự ra dấu hỏi còn hơn giết máy chủ giữa lần đo.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _force_utf8_output()
    p = argparse.ArgumentParser(description="Mock OpenAI API tại chỗ để đo tải (KHÔNG tốn tiền).")
    p.add_argument("--host", default="127.0.0.1", help="Địa chỉ nghe")
    p.add_argument("--port", type=int, default=9099, help="Cổng nghe")
    p.add_argument("--parser-delay", type=float, default=9.4, help="Độ trễ giả cho model parser (giây)")
    p.add_argument("--ranker-delay", type=float, default=24.7, help="Độ trễ giả cho model ranker (giây)")
    p.add_argument("--embed-delay", type=float, default=0.3, help="Độ trễ giả cho embedding (giây)")
    p.add_argument("--default-delay", type=float, default=1.0, help="Độ trễ cho model KHÔNG nhận ra")
    p.add_argument("--parser-model", default="gpt-4.1-mini", help="Khớp PARSER_MODEL trong .env")
    p.add_argument("--ranker-model", default="gpt-5-mini", help="Khớp RANKER_MODEL trong .env")
    p.add_argument("--embed-model", default="text-embedding-3-small", help="Khớp EMBEDDING_MODEL")
    p.add_argument("--dim", type=int, default=1536, help="Số chiều vector — phải khớp EMBEDDING_DIM")
    p.add_argument("--jitter", type=float, default=0.15,
                   help="Nhiễu độ trễ dạng phân số ±(vd 0.15 = ±15%%) — tránh N request về đích lockstep")
    p.add_argument("--seed", type=int, default=1234,
                   help="Seed random. Lặp lại được CHUỖI rút, KHÔNG lặp lại được ai nhận số nào "
                        "(thứ tự luồng chạm khoá là ngẫu nhiên) — đừng coi đây là run tất định")
    p.add_argument("--failure-rate", type=float, default=0.0,
                   help="Tỉ lệ request chat bị trả 429 (đo hành vi khi provider bóp quota)")
    p.add_argument("--allow-remote", action="store_true",
                   help="Cho phép nghe ngoài loopback (client sẽ gửi OPENAI_API_KEY THẬT tới đây)")
    p.add_argument("--confirm", action="store_true",
                   help="BẮT BUỘC — xác nhận đã hiểu dữ liệu trả về là BỊA")
    args = p.parse_args()

    if args.host not in ("127.0.0.1", "localhost", "::1") and not args.allow_remote:
        sys.exit(
            f"Từ chối nghe trên {args.host!r} — thêm --allow-remote nếu CHỦ ĐÍCH muốn vậy.\n"
            "Lý do: client không biết đây là mock nên vẫn gửi OPENAI_API_KEY THẬT trong header, và "
            "bất kỳ ai trong mạng cũng nhận được CV bịa từ endpoint này."
        )
    if not args.confirm:
        sys.exit(
            "Cần --confirm. Mock này trả CV BỊA và điểm CỐ ĐỊNH. Nếu backend đang trỏ vào đây mà bạn\n"
            "chạy demo thật, hệ thống sẽ ghi hồ sơ bịa vào DB và có thể GỬI EMAIL THẬT dựa trên điểm\n"
            "bịa (gate auto-mời/auto-từ-chối). Đọc docstring đầu file trước khi chạy."
        )
    if not 0.0 <= args.failure_rate <= 1.0:
        sys.exit("--failure-rate phải nằm trong [0, 1].")
    if args.jitter < 0:
        sys.exit("--jitter phải >= 0.")
    if args.dim <= 0:
        sys.exit("--dim phải > 0.")

    cfg = MockConfig(args)
    stats = MockStats()
    vectors = VectorFactory(args.dim, args.seed)
    handler = build_handler(cfg, stats, vectors, threading.Lock(), random.Random(args.seed))

    # daemon_threads: một luồng/kết nối, và luồng treo KHÔNG được giữ tiến trình sống khi Ctrl-C.
    # Nếu mock tự tuần tự hoá thì CHÍNH NÓ thành nút thắt và mọi số đo đều là rác.
    ThreadingHTTPServer.daemon_threads = True
    ThreadingHTTPServer.allow_reuse_address = True  # Ctrl-C rồi chạy lại ngay, không dính TIME_WAIT.
    ThreadingHTTPServer.request_queue_size = _LISTEN_BACKLOG  # xem `_LISTEN_BACKLOG` — BẮT BUỘC.
    server = ThreadingHTTPServer((args.host, args.port), handler)

    print_banner(args)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        print_summary(stats, cfg)


if __name__ == "__main__":
    main()
