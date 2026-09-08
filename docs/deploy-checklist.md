# Checklist triển khai prod (Render + Vercel)

> Tách khỏi `.env.example` ngày 08/09/2026. Lý do: khối này **lặp lại giá trị của gần như mọi biến**
> đã khai ở trên trong chính file đó — hai nguồn chân lý cho cùng một con số, sửa một chỗ quên chỗ kia.
> `.env.example` nay chỉ còn là file MẪU (tên biến + giá trị dev); còn đây là RUNBOOK (đặt gì trên nền tảng).

## Env đặt trên Render (slice 13 §4.2)

File .env KHÔNG được copy vào image (xem .dockerignore) — trên Render mọi giá trị đặt ở
Environment của service. Dán checklist này rồi điền. Giá trị KHÁC dev được đánh dấu ⚠.

### Chạy
  ⚠ APP_ENV=production            ⚠ HOST=0.0.0.0   (PORT: Render tự cấp, ĐỪNG đặt tay)
    ENABLE_LLM=true               ⚠ ENABLE_DEV_ENDPOINTS=false

### Cross-domain: 3 biến này sai là HR đăng nhập xong mất phiên (rủi ro #1)
  ⚠ CORS_ORIGINS=https://<app>.vercel.app       (origin frontend, KHÔNG '/' cuối, KHÔNG '*')
  ⚠ COOKIE_SECURE=true      ⚠ COOKIE_SAMESITE=none      COOKIE_DOMAIN=   (để trống)
  ⚠ FRONTEND_BASE_URL=https://<app>.vercel.app  (magic-link trong email screener trỏ về đây)
    → Phía Vercel còn 3 biến PHẢI khớp với khối này (BACKEND_ORIGIN, NEXT_PUBLIC_API_BASE,
      NEXT_PUBLIC_PUBLIC_API_BASE) — chúng KHÔNG nằm trong file này. Xem
      `apps/dashboard/.env.example`. Đặc biệt `CORS_ORIGINS` ở trên phải chứa origin Vercel,
      nếu không đường nộp CV gọi thẳng backend sẽ bị chặn CORS.

### Secret MỚI cho prod (KHÔNG tái dùng giá trị dev)
  ⚠ JWT_SECRET=            (sinh mới: openssl rand -hex 32)
    JWT_EXPIRY_MINUTES=480    AUTH_COOKIE_NAME=ars_session
    (HR_ADMIN_EMAIL / HR_ADMIN_PASSWORD: **KHÔNG đặt trên service**. Backend lúc chạy KHÔNG hề
     đọc chúng — đăng nhập tra bảng hr_user rồi so bcrypt. Chỉ `scripts/seed_hr_admin.py` dùng,
     nên chỉ cần có ở NƠI CHẠY script. Để lại trên dashboard = mật khẩu admin nằm phơi vĩnh viễn
     mà chẳng đổi lấy chức năng gì. Xem mục "Seed tài khoản HR" bên dưới.)

### Hạ tầng
  ⚠ DATABASE_URL=          (Neon branch PROD RIÊNG — đừng trỏ vào DB dev)
    QDRANT_URL=  QDRANT_API_KEY=  QDRANT_COLLECTION=
    (cân nhắc QDRANT_COLLECTION riêng cho prod để vector dev không lẫn vào)

### Lưu CV: BẮT BUỘC r2 trên prod
  ⚠ STORAGE_BACKEND=r2     (đĩa Render là ephemeral — local = MẤT CV mỗi lần redeploy)
    R2_ACCOUNT_ID=  R2_ACCESS_KEY_ID=  R2_SECRET_ACCESS_KEY=  R2_BUCKET=  R2_ENDPOINT=
    Bucket PHẢI PRIVATE (NFR-4).

### LLM + email
    OPENAI_API_KEY=  PARSER_MODEL=gpt-4.1-mini
    RANKER_MODEL=gpt-5-mini  RANKER_REASONING_EFFORT=low   (bỏ effort là ranker hỏng)
    RUBRIC_SUGGEST_MODEL=gpt-5-mini  RUBRIC_SUGGEST_REASONING_EFFORT=low  RUBRIC_SUGGEST_MAX_RETRIES=3
    EMBEDDING_MODEL=text-embedding-3-small  EMBEDDING_DIM=1536
    RESEND_API_KEY=  EMAIL_FROM=            (domain đã xác thực nếu gửi cho người ngoài)
    EMAIL_REPLY_TO=                (địa chỉ HR thật nhận Reply — vừa UX vừa tín hiệu deliverability)
    EMAIL_MIN_INTERVAL_MS=550  EMAIL_MAX_RETRIES=3
  ⚠ RESEND_WEBHOOK_SECRET=       (lấy khi tạo webhook trên Resend — Settings → Webhooks. THIẾU
    biến này thì /api/webhooks/resend trả 503 cho MỌI sự kiện; Resend thử lại vài lần rồi BỎ
    CUỘC ⇒ MẤT TÍN HIỆU BOUNCE vĩnh viễn cho những gì gửi trong lúc thiếu secret — đặt biến này
    TRƯỚC khi tạo webhook, và webhook trên Resend PHẢI trỏ https://<backend>/api/webhooks/resend)
    RESEND_WEBHOOK_TOLERANCE_SECONDS=300  RESEND_WEBHOOK_MAX_BYTES=65536

### Ngưỡng + hardening
    CONFIDENCE_THRESHOLD=0.6  SCORE_PASS_THRESHOLD=60  SCORE_NEAR_BAND=10
    SCREENER_DEADLINE_HOURS=72  SCREENER_REMINDER_HOURS=24
    SCREENER_SWEEP_INTERVAL_SECONDS=600
    STUCK_APPLICATION_TIMEOUT_MINUTES=30   (lưới cứu hồ sơ kẹt — xem ghi chú ở trên)
    BOOKING_TIMEZONE=Asia/Ho_Chi_Minh  BOOKING_WORK_DAYS=1-5  BOOKING_WORK_START=08:00
    BOOKING_WORK_END=17:30  BOOKING_LUNCH=12:00-13:30  BOOKING_DURATION_MINUTES=60
    BOOKING_BUFFER_MINUTES=15  BOOKING_LEAD_TIME_HOURS=24  BOOKING_MAX_PER_DAY=6
    BOOKING_WINDOW_DAYS=21  BOOKING_SLOTS_OFFERED=5  BOOKING_HOLD_MINUTES=5
    BOOKING_LINK_TTL_HOURS=72  CALENDAR_PROVIDER=ics
    BOOKING_INTERVIEW_REMINDER_HOURS=24  BOOKING_REMINDER_HOURS=24
                              (giờ làm việc của CÔNG TY, không phải của máy chủ — máy chủ chạy UTC)
                              MAX_PER_DAY × ngày làm trong WINDOW = kho khung giờ; mỗi lượt ứng
                              viên mở link giữ SLOTS_OFFERED khung ⇒ đặt quá thấp là lịch cạn sớm)
    TRUST_PROXY_HEADERS=            (để trống: tự bật vì APP_ENV=production)
    PROXY_CLIENT_IP_HEADER=cf-connecting-ip   (Render có Cloudflare → khoá quota theo IP client
                              thật; log "Rate-limit: khóa quota" phải ra IP khách, KHÔNG phải 10.x)
    PROXY_TRUSTED_HOPS=2           (chỉ là dự phòng khi thiếu CF-Connecting-IP)
    RATE_LIMIT_ENABLED=true  RATE_LIMIT_LOGIN_MAX=10  RATE_LIMIT_PUBLIC_MAX=20
    MAX_REQUEST_BYTES=12582912
    CHECKPOINTER_POOL_MAX_IDLE_SECONDS=120   (< ~300s autosuspend Neon → pool tự đóng kết nối
                              nhàn rỗi trước khi Neon giết; kèm check-on-borrow, sửa pipeline hỏng)

### Seed tài khoản HR trên prod (KHÔNG cần Shell — gói free của Render không có)
    Chạy TỪ MÁY BẠN, trỏ thẳng vào DB prod; env chỉ sống trong đúng lệnh này:
      DATABASE_URL='<url prod>' HR_ADMIN_EMAIL='...' HR_ADMIN_PASSWORD='...' \
        uv run --directory apps/backend python ../../scripts/seed_hr_admin.py
    IDEMPOTENT và CỐ Ý không đổi mật khẩu của tài khoản đã có (tránh ghi đè nhầm) — nên chạy lại
    với mật khẩu khác sẽ KHÔNG đổi được mật khẩu; muốn đổi thì phải cập nhật hàng hr_user.

### Render: cấu hình service (KHÔNG phải env var)
    Health Check Path = /api/health/live    ← KHÔNG phải /api/health (bản kiểm sâu ping cả 2
    dịch vụ; Render ping vài giây/lần sẽ giữ Neon không bao giờ tự ngủ, đốt sạch compute-hours)
    Dockerfile Path = ./Dockerfile · Build Context = .  · Instance: tiến-trình-bền (không serverless)

---

## Cấu hình nghiệp vụ KHÔNG còn nằm ở env (từ 08/09/2026)

39 hằng số nghiệp vụ — ngưỡng chấm điểm, mốc nhắc/timeout, toàn bộ `BOOKING_*`, nhịp gửi email —
đã chuyển sang bảng `app_config` và sửa được tại **`/system` → tab Cấu hình** (yêu cầu đăng nhập HR).
Chúng KHÔNG cần đặt trên Render nữa.

**Thứ tự ưu tiên khi khởi động:** hàng trong `app_config` › biến môi trường › mặc định trong
`app/core/config.py`. Bảng rỗng = chạy hoàn toàn theo mặc định của code, và **chỉ hàng khác mặc định
mới được lưu** — nhờ vậy đổi mặc định trong code sẽ tự lan tới mọi môi trường chưa từng chỉnh tay.

Hệ quả cần biết khi vận hành: đặt một trong 39 biến đó lên Render vẫn có tác dụng, **nhưng chỉ tới
lần đầu ai đó bấm Lưu ở `/system`** — từ đó hàng trong DB thắng. Nếu thấy "đã sửa env mà không đổi
gì", hãy mở `/system` xem giá trị đang chạy thật.

Migration bắt buộc: `alembic upgrade head` (revision `e2f3a4b5c6d7`). Đã chạy trên cả DB dev và prod
ngày 08/09/2026.
