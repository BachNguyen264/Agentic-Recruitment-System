"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import type { ScreenerForm } from "@ars/shared-types";
import Link from "next/link";
import { SuccessPanel } from "@/components/SuccessPanel";
import { BackArrow, btn, EmptyState, Field, inputClass } from "@/components/ui";
import { getScreener, submitScreener } from "@/lib/api";

// Trang trả lời sàng lọc qua magic-link (PRD §7.3, §10). Ứng viên là KHÁCH: chỉ thấy CÂU HỎI +
// tên vị trí — không rubric, không điểm, không trạng thái hồ sơ.
//
// Token sai / hết hạn / đã dùng rồi (one-time) → backend trả lỗi kèm message rõ; hiện thông báo,
// KHÔNG dựng form.
export default function ScreeningPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  // KHOÁ CHẶT query — tải MỘT lần rồi thôi. Hai lý do, cả hai đều làm ứng viên mất bài:
  //  1. Rate-limit theo IP ở đường công khai: refetch mỗi lần focus lại tab sẽ đốt quota, tới lúc
  //     bấm "Gửi câu trả lời" thì 429 → quá hạn → hồ sơ bị xử như KHÔNG PHẢN HỒI.
  //  2. NGHIÊM TRỌNG HƠN — refetchOnReconnect/refetchOnMount mặc định BẬT: ứng viên đang gõ dở,
  //     mạng chớp (wifi ↔ 4G) → query chạy lại → nếu sweep timeout (08c) vừa đóng phiên thì query
  //     chuyển sang isError, nhánh formQuery.data biến mất và TOÀN BỘ chữ đã gõ bị xoá khỏi màn
  //     hình. Guest không có tài khoản để khiếu nại.
  const formQuery = useQuery<ScreenerForm>({
    queryKey: ["screener", token],
    queryFn: () => getScreener(token),
    enabled: Boolean(token),
    retry: false,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    refetchOnReconnect: false,
  });

  const [answers, setAnswers] = useState<Record<number, string>>({});
  const questions = formQuery.data?.questions ?? [];

  const mutation = useMutation({
    mutationFn: () => submitScreener(token, questions.map((_, i) => answers[i] ?? "")),
  });

  // ── Sau khi gửi thành công — KHÔNG hiện điểm/trạng thái ──
  if (mutation.isSuccess) {
    return (
      <main>
        <SuccessPanel
          title="Đã ghi nhận câu trả lời"
          action={
            <Link href="/apply" className={btn("secondary")}>
              <BackArrow /> Về cổng tuyển dụng
            </Link>
          }
        >
          Bộ phận Tuyển dụng sẽ xem xét và liên hệ với bạn qua email. Cảm ơn bạn!
        </SuccessPanel>
      </main>
    );
  }

  return (
    <main>
      {formQuery.isLoading && (
        <p role="status" className="text-[13px] text-ink/50">
          Đang tải câu hỏi…
        </p>
      )}

      {/* Message do BACKEND quyết (services/screening.py phân biệt 404 sai / 409 đã gửi / 410 hết
          hạn) và đã được viết cẩn thận — in NGUYÊN VĂN, không diễn giải lại. Đặc biệt ca hết hạn
          backend cố ý TRẤN AN ("hồ sơ vẫn đang được xem xét") vì hồ sơ thật sự đi tiếp sang HR;
          thêm câu "liên kết có thể đã hết hạn hoặc đã được dùng" vào đây là tự mâu thuẫn và làm
          ứng viên tưởng mình đã trượt. Dòng phụ bên dưới giữ TRUNG TÍNH để đúng cho cả ba ca. */}
      {formQuery.isError && (
        <div
          role="alert"
          className="rounded-xl border-2 border-divider bg-surface px-6 py-10 text-center"
        >
          <p className="font-heading text-[15px] font-bold">
            {String((formQuery.error as Error)?.message) || "Liên kết không hợp lệ."}
          </p>
          <p className="mx-auto mt-1.5 max-w-[46ch] text-[13px] text-ink/55">
            Nếu bạn cho rằng đây là nhầm lẫn, vui lòng trả lời email chúng tôi đã gửi.
          </p>
        </div>
      )}

      {formQuery.data && (
        <>
          <p className="eyebrow mb-1.5">Magic-link · không cần mật khẩu</p>
          <h1 className="text-[26px] sm:text-[30px]">Câu hỏi sàng lọc</h1>
          <p className="mt-2 max-w-[62ch] text-[13px] leading-relaxed text-ink/55">
            Vị trí: <strong className="font-semibold text-ink">{formQuery.data.job_title}</strong>.
            Vui lòng trả lời để chúng tôi tiếp tục xem xét hồ sơ của bạn.
          </p>

          {questions.length === 0 ? (
            <div className="mt-5">
              <EmptyState>Liên kết này không có câu hỏi nào.</EmptyState>
            </div>
          ) : (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (!mutation.isPending) mutation.mutate();
              }}
              className="mt-5"
            >
              <div className="flex flex-col gap-4">
                {questions.map((q, i) => (
                  <Field key={i} label={`${i + 1}. ${q}`} htmlFor={`q-${i}`}>
                    <textarea
                      id={`q-${i}`}
                      rows={3}
                      value={answers[i] ?? ""}
                      onChange={(e) => setAnswers((prev) => ({ ...prev, [i]: e.target.value }))}
                      disabled={mutation.isPending}
                      maxLength={5000}
                      className={`${inputClass} min-h-16 bg-canvas`}
                    />
                  </Field>
                ))}
              </div>

              {mutation.isError && (
                <p
                  role="alert"
                  className="mt-4 rounded-xl border-2 border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700"
                >
                  {String((mutation.error as Error)?.message) ||
                    "Không gửi được câu trả lời. Vui lòng thử lại."}
                </p>
              )}

              <button type="submit" disabled={mutation.isPending} className={btn("primary", "mt-4")}>
                {mutation.isPending ? "Đang gửi…" : "Gửi câu trả lời"}
              </button>
            </form>
          )}
        </>
      )}
    </main>
  );
}
