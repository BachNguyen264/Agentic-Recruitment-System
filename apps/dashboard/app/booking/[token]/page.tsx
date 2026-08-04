"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { BookingConfirmResult, BookingView } from "@ars/shared-types";
import { SuccessPanel } from "@/components/SuccessPanel";
import { btn, EmptyState } from "@/components/ui";
import { BookingApiError, confirmBooking, getBooking } from "@/lib/api";

// Trang ứng viên TỰ CHỌN giờ phỏng vấn (PRD §10b). Ứng viên là KHÁCH: chỉ thấy tên vị trí + các
// khung giờ — không điểm, không rubric, không trạng thái hồ sơ.
//
// Ba trạng thái đặc thù của trang này, cả ba đều phải xử lý tử tế vì người đọc vừa được MỜI phỏng vấn:
//   1. `already_booked` — mở lại link sau khi đã đặt (token KHÔNG one-time) → hiện lịch đã đặt.
//   2. Hết chỗ giữ (10 phút, KHÔNG gia hạn) → nói rõ + nút tải danh sách mới, đừng đổ lỗi người dùng.
//   3. Thua race (409) → tự làm mới danh sách ngay, không bắt họ tự mò.

const VN_TZ = "Asia/Ho_Chi_Minh";

// LUÔN hiển thị theo giờ Việt Nam, kèm THỨ. Để trình duyệt tự dùng múi giờ của máy là mời gọi tai
// nạn: một ứng viên đang ở nước ngoài sẽ đọc ra giờ khác với giờ hẹn thật. Có thứ trong chuỗi thì
// "06/08" không còn cửa bị đọc nhầm thành ngày 8 tháng 6.
function formatSlot(iso: string): string {
  const at = new Date(iso);
  const time = new Intl.DateTimeFormat("vi-VN", {
    timeZone: VN_TZ, hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(at);
  const date = new Intl.DateTimeFormat("vi-VN", {
    timeZone: VN_TZ, weekday: "long", day: "2-digit", month: "2-digit", year: "numeric",
  }).format(at);
  return `${time} · ${date}`;
}

function useCountdown(deadline: string | null): number | null {
  const target = useMemo(() => (deadline ? new Date(deadline).getTime() : null), [deadline]);
  const [left, setLeft] = useState<number | null>(() =>
    target === null ? null : Math.max(0, target - Date.now()),
  );

  useEffect(() => {
    if (target === null) {
      setLeft(null);
      return;
    }
    setLeft(Math.max(0, target - Date.now()));
    const id = setInterval(() => setLeft(Math.max(0, target - Date.now())), 1000);
    return () => clearInterval(id);
  }, [target]);

  return left;
}

function mmss(ms: number): string {
  const total = Math.floor(ms / 1000);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export default function BookingPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  // Không tự refetch (focus/reconnect/mount): mỗi lần tải lại là một lượt gọi backend, và đồng hồ
  // đếm ngược nhảy lại làm người dùng tưởng mình vừa được gia hạn. Làm mới CHỈ khi có lý do rõ
  // ràng: hết hạn giữ chỗ, hoặc thua race.
  const query = useQuery<BookingView>({
    queryKey: ["booking", token],
    queryFn: () => getBooking(token),
    enabled: Boolean(token),
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    refetchOnReconnect: false,
  });

  const [selected, setSelected] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const view = query.data;
  const msLeft = useCountdown(view?.already_booked ? null : (view?.hold_expires_at ?? null));
  const holdExpired = msLeft !== null && msLeft <= 0;

  const mutation = useMutation<BookingConfirmResult, Error, number>({
    mutationFn: (bookingId) => confirmBooking(token, bookingId),
    onError: async (err) => {
      // 409 = giờ vừa bị người khác đặt, HOẶC chỗ giữ đã hết hạn. Cả hai đều xử lý giống nhau:
      // nói thật chuyện gì xảy ra rồi đưa danh sách MỚI ngay, đừng để họ bấm lại vào ô đã chết.
      if (err instanceof BookingApiError && err.status === 409) {
        setNotice(err.message);
        setSelected(null);
        await query.refetch();
      }
    },
  });

  async function refresh(): Promise<void> {
    setNotice(null);
    setSelected(null);
    await query.refetch();
  }

  // ── Đặt xong ─────────────────────────────────────────────────────────────
  if (mutation.isSuccess) {
    const done = mutation.data;
    return (
      <main>
        <SuccessPanel title="Đã xác nhận lịch phỏng vấn">
          Buổi phỏng vấn vị trí <strong>{done.job_title}</strong> của bạn diễn ra lúc{" "}
          <strong>{formatSlot(done.start_at)}</strong> (giờ Việt Nam).
          {/* Nói THẬT về email: hứa một thư xác nhận chưa gửi được đúng là kiểu "trạng thái nói
              dối" mà cả hệ thống này tránh. Lịch đã chốt trong cả hai trường hợp. */}
          {done.email_sent ? (
            <> Chúng tôi đã gửi thư xác nhận kèm tệp lịch (.ics) tới email của bạn.</>
          ) : (
            <> Lịch đã được ghi nhận. Bộ phận Tuyển dụng sẽ liên hệ lại với bạn để xác nhận.</>
          )}
        </SuccessPanel>
      </main>
    );
  }

  return (
    <main>
      {query.isLoading && (
        <p role="status" className="text-[13px] text-ink/65">
          Đang tải khung giờ…
        </p>
      )}

      {/* Message do BACKEND quyết (booking_service phân biệt 404 link sai / 410 hết hạn hoặc đã
          huỷ) và đã viết cẩn thận — in NGUYÊN VĂN, không diễn giải lại. */}
      {query.isError && (
        <div role="alert" className="rounded-xl border-2 border-divider bg-surface px-6 py-10 text-center">
          <p className="font-heading text-[15px] font-bold">
            {String((query.error as Error)?.message) || "Liên kết không hợp lệ."}
          </p>
          <p className="mx-auto mt-1.5 max-w-[46ch] text-[13px] text-ink/65">
            Nếu bạn cho rằng đây là nhầm lẫn, vui lòng trả lời email chúng tôi đã gửi.
          </p>
        </div>
      )}

      {/* ── Đã đặt rồi: KHÔNG render danh sách chọn ── */}
      {view?.already_booked && view.booked_start_at && (
        <SuccessPanel title="Bạn đã đặt lịch phỏng vấn">
          Buổi phỏng vấn vị trí <strong>{view.job_title}</strong> đã được đặt lúc{" "}
          <strong>{formatSlot(view.booked_start_at)}</strong> (giờ Việt Nam). Nếu cần thay đổi, vui
          lòng trả lời email xác nhận chúng tôi đã gửi.
        </SuccessPanel>
      )}

      {view && !view.already_booked && (
        <>
          <h1 className="text-[26px] sm:text-[30px]">Chọn giờ phỏng vấn</h1>
          <p className="mt-2 max-w-[62ch] text-[15px] leading-relaxed text-ink/70">
            Chào <strong className="font-semibold text-ink">{view.candidate_name}</strong>, vui lòng
            chọn một khung giờ phù hợp cho buổi phỏng vấn vị trí{" "}
            <strong className="font-semibold text-ink">{view.job_title}</strong>. Tất cả thời gian
            theo giờ Việt Nam.
          </p>

          {view.slots.length === 0 ? (
            // KHÔNG để trang trắng: lịch tạm đầy là chuyện của hệ thống, không phải lỗi ứng viên.
            <div className="mt-5">
              <EmptyState>
                Hiện chưa có khung giờ trống. Bộ phận Tuyển dụng sẽ liên hệ trực tiếp với bạn để sắp
                xếp lịch phỏng vấn.
              </EmptyState>
            </div>
          ) : (
            <>
              {/* Đồng hồ đếm ngược BẮT BUỘC: chỗ giữ 10 phút và KHÔNG được gia hạn khi tải lại
                  (quyết định SCH-1) — không hiện thì người dùng bị bất ngờ đúng lúc bấm xác nhận. */}
              {msLeft !== null && !holdExpired && (
                <p className="mt-4 text-[13px] text-ink/65" role="status">
                  Các khung giờ dưới đây được giữ cho bạn trong{" "}
                  <strong className="font-semibold tabular-nums text-ink">{mmss(msLeft)}</strong>.
                </p>
              )}

              {holdExpired && (
                <div
                  role="alert"
                  className="mt-4 rounded-xl border-2 border-divider bg-surface px-4 py-3 text-[13px]"
                >
                  <p className="font-semibold">Thời gian giữ chỗ đã hết.</p>
                  <p className="mt-1 text-ink/65">
                    Không sao cả — bạn chỉ cần tải danh sách mới để chọn lại.
                  </p>
                  <button type="button" onClick={refresh} className={btn("primary", "mt-3")}>
                    Tải danh sách mới
                  </button>
                </div>
              )}

              {notice && !holdExpired && (
                <p
                  role="alert"
                  className="mt-4 rounded-xl border-2 border-amber-200 bg-amber-50 px-4 py-3 text-[13px] text-amber-800"
                >
                  {notice} Danh sách bên dưới đã được cập nhật.
                </p>
              )}

              <fieldset disabled={holdExpired || mutation.isPending} className="mt-5">
                <legend className="sr-only">Khung giờ phỏng vấn</legend>
                <div className="flex flex-col gap-2.5">
                  {view.slots.map((slot) => (
                    <label
                      key={slot.booking_id}
                      className={`flex cursor-pointer items-center gap-3 rounded-xl border-2 px-4 py-3 text-[15px] transition ${
                        selected === slot.booking_id
                          ? "border-ink bg-surface font-semibold"
                          : "border-divider bg-canvas hover:border-ink/40"
                      } ${holdExpired ? "opacity-50" : ""}`}
                    >
                      <input
                        type="radio"
                        name="slot"
                        value={slot.booking_id}
                        checked={selected === slot.booking_id}
                        onChange={() => setSelected(slot.booking_id)}
                        className="h-4 w-4 accent-ink"
                      />
                      <span>{formatSlot(slot.start_at)}</span>
                    </label>
                  ))}
                </div>
              </fieldset>

              {/* Lỗi KHÔNG phải 409 (mạng, 500…): 409 đã được xử lý êm bằng `notice` + làm mới. */}
              {mutation.isError &&
                !(mutation.error instanceof BookingApiError && mutation.error.status === 409) && (
                  <p
                    role="alert"
                    className="mt-4 rounded-xl border-2 border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700"
                  >
                    {String((mutation.error as Error)?.message) ||
                      "Không xác nhận được khung giờ. Vui lòng thử lại."}
                  </p>
                )}

              <button
                type="button"
                disabled={selected === null || holdExpired || mutation.isPending}
                onClick={() => selected !== null && mutation.mutate(selected)}
                className={btn("primary", "mt-4")}
              >
                {mutation.isPending ? "Đang xác nhận…" : "Xác nhận khung giờ"}
              </button>
            </>
          )}
        </>
      )}
    </main>
  );
}
