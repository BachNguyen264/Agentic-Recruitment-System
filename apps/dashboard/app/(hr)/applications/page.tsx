"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ApplicationListItem } from "@ars/shared-types";
import { btn, inputClass, PageHeader, Tag } from "@/components/ui";
import { getApplications, getPipeline } from "@/lib/api";
import {
  BUCKET_FILTERS,
  bucketTotal,
  STATUSES_IN_BUCKET,
  applicationStatusLabel,
  applicationStatusTone,
  isEmailFlag,
  type StatusBucket,
} from "@/lib/applications";
import { useJobTitles } from "@/lib/useJobTitles";
import { formatVnDateTime } from "@/lib/datetime";

// Một trang. 50 dòng là bảng đọc được mà không cần ảo hoá (mỗi dòng nay chỉ ~800 B vì danh sách
// không còn chở parsed_data/score_breakdown — xem `response_model_exclude` ở routes/applications.py).
const PAGE_SIZE = 50;

function initialsOf(email: string): string {
  const name = email.split("@")[0] ?? "";
  const parts = name.split(/[._-]+/).filter(Boolean);
  return ((parts.length >= 2 ? parts[0][0] + parts[1][0] : name.slice(0, 2)) || "??").toUpperCase();
}

// Ô trạng thái — dùng chung cho bảng (desktop) và thẻ (điện thoại). Hai bản chép tay song song
// chính là cách một cờ email thứ tư được thêm vào một bên rồi im lặng vắng mặt ở bên kia.
//
// EMAIL-1: ba cờ email KHÁC cờ "cần chú ý" ở chỗ chúng hiện với MỌI trạng thái. Ca đáng lo nhất
// chính là ca đã quyết xong: "Đã từ chối" / "Đã hẹn phỏng vấn" mà thư không tới nơi thì dòng trạng
// thái đó đang nói dối, và nếu giấu nhãn đi vì hồ sơ "đã xong" thì không ai phát hiện ra nữa.
// Bounce và complaint là HAI nhãn riêng vì đòi hai cách xử TRÁI NGƯỢC: bounce ⇒ tìm địa chỉ đúng
// rồi liên hệ lại; complaint ⇒ NGỪNG gửi cho người này. Complaint hiện TRƯỚC vì hành động cấp bách
// hơn (đồng bộ thứ tự với trang chi tiết + ReviewCard).
//
// Cờ "cần chú ý" thì ngược lại — nó là chỉ báo HÀNH ĐỘNG cho HR nên CHỈ hiện khi còn chờ quyết.
function StatusCell({ a }: { a: ApplicationListItem }) {
  const otherFlags = a.uncertainty_flags.filter((f) => !isEmailFlag(f));
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Tag tone={applicationStatusTone(a)}>{applicationStatusLabel(a)}</Tag>
      {a.email_complained && <Tag tone="danger">🚫 Đã báo cáo spam</Tag>}
      {a.email_bounced && <Tag tone="danger">⚠ Email không gửi được</Tag>}
      {a.email_send_failed && <Tag tone="danger">⛔ Hệ thống chưa gửi được thư</Tag>}
      {a.status === "PENDING_REVIEW" && otherFlags.length > 0 && (
        <span className="text-xs font-semibold text-accent">{otherFlags.join(" · ")}</span>
      )}
    </div>
  );
}

export default function ApplicationsPage() {
  const [bucket, setBucket] = useState<StatusBucket | "all">("all");
  const [offset, setOffset] = useState(0);
  // `search` = thứ đang gõ; `term` = thứ ĐÃ gửi đi. Tách ra để mỗi phím gõ không thành một request:
  // router HR không nằm trong xô rate-limit nào nên gõ 20 ký tự = 20 câu SQL toàn bảng.
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setTerm(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);
  const searching = term.length > 0;

  // Đổi rổ = xem một TẬP khác, nên phải về trang 1. Không reset thì bấm "Từ chối" lúc đang ở trang 3
  // sẽ ra bảng rỗng dù có hồ sơ bị từ chối — trông hệt như "không có dữ liệu".
  const selectBucket = (b: StatusBucket | "all") => {
    setBucket(b);
    setOffset(0);
  };

  // Lọc chạy ở SERVER. Trước B1 nó là `apps.filter(...)` trên "100 hồ sơ mới nhất" — nghĩa là chip
  // "Từ chối (0)" không phân biệt được "hệ thống chưa từ chối ai" với "mọi ca từ chối đều nằm ngoài
  // cửa sổ 100 dòng". Hai câu trả lời trái ngược nhau, cùng một giao diện.
  const { data, isLoading, isError, error } = useQuery<ApplicationListItem[]>({
    queryKey: ["applications", "list", bucket, term, offset],
    queryFn: () =>
      getApplications({ status: STATUSES_IN_BUCKET[bucket], q: term, limit: PAGE_SIZE, offset }),
    refetchInterval: 15_000, // pipeline chạy nền — cập nhật khi CV chuyển trạng thái.
    placeholderData: (prev) => prev,
  });

  // Số trên chip + tổng lấy từ `counts` (GROUP BY TOÀN BẢNG), không đếm trong trang đang xem.
  const { data: pipeline, isError: pipelineError } = useQuery({
    queryKey: ["pipeline"],
    queryFn: getPipeline,
    refetchInterval: 15_000,
  });
  // Tên vị trí cho từng hồ sơ. Dùng hook chung vì nó nạp CẢ JD đã lưu trữ — hồ sơ cũ gắn vào JD đã
  // lưu trữ mà chỉ hỏi rổ active thì hiện "JD #id" vĩnh viễn, đúng lúc cần đọc tên nhất.
  const jobTitle = useJobTitles();

  // `data` ĐÃ được server lọc theo rổ → không lọc lại ở client (lọc hai lần chính là bug cũ).
  const filtered = data ?? [];
  const total = searching ? null : bucketTotal(pipeline?.counts, bucket);
  // ĐƯỜNG LÙI khi không biết tổng — `/pipeline` hỏng, hoặc đang tìm kiếm (counts đếm toàn bảng nên
  // không nói gì về tập kết quả tìm được). Không có nhánh này thì `total == null` làm nút "Trang
  // sau" biến mất HOÀN TOÀN: người dùng bị nhốt ở trang 1 mà màn hình trông như đã hết dữ liệu.
  // Một trang đầy ĐÚNG bằng PAGE_SIZE là dấu hiệu đủ tin cậy rằng còn trang nữa.
  const hasMore =
    total != null ? offset + filtered.length < total : filtered.length === PAGE_SIZE;

  return (
    <div className="mx-auto max-w-[1120px] px-4 pb-8 pt-6 sm:px-8">
      <PageHeader
        eyebrow="Danh sách hồ sơ"
        title="Ứng viên"
        description="Toàn bộ CV đã nộp kèm điểm và trạng thái theo bốn rổ pipeline (PRD §13). Bấm một hàng để mở chi tiết điểm và agent trace."
      />

      {/* Bộ lọc theo rổ trạng thái */}
      <div className="flex flex-wrap gap-2">
        {BUCKET_FILTERS.map((f) => {
          // Số TOÀN HỆ THỐNG (GROUP BY), không phải số đếm được trong trang đang xem. `null` khi
          // chưa tải xong `counts` → hiện "…" thay vì "(0)": "(0)" là một KHẲNG ĐỊNH sai.
          const n = bucketTotal(pipeline?.counts, f.key);
          const active = bucket === f.key;
          return (
            <button
              key={f.key}
              type="button"
              onClick={() => selectBucket(f.key)}
              aria-pressed={active}
              className={`rounded-lg border-2 px-3 py-1.5 text-[13px] font-semibold transition-colors ${
                active
                  ? "border-accent bg-accent text-white"
                  : "border-divider text-ink/70 hover:bg-ink/[0.06]"
              }`}
            >
              {f.label}{" "}
              <span className={active ? "text-white" : "text-ink/65"}>({n ?? "…"})</span>
            </button>
          );
        })}
      </div>

      {/* U6: tìm ở SERVER (`?q=`), không lọc trang đang xem — ứng viên cần tìm hay nằm ở trang 3. */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <label htmlFor="app-search" className="text-[13px] font-semibold text-ink/70">
          Tìm theo email
        </label>
        <input
          id="app-search"
          type="search"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setOffset(0);
          }}
          placeholder="vd: an.nguyen@"
          className={`${inputClass} max-w-[280px]`}
        />
        {searching && (
          <button type="button" onClick={() => { setSearch(""); setOffset(0); }} className={btn("ghost")}>
            Xoá tìm kiếm
          </button>
        )}
      </div>

      {/* `/pipeline` hỏng thì mọi con số trên chip và dòng "đang hiện X trong Y" đều không có. Nói
          thẳng ra, thay vì để người dùng tự đoán vì sao các số biến thành "…". */}
      {pipelineError && (
        <p role="status" className="mt-3 text-[13px] text-amber-700">
          Chưa đọc được tổng số hồ sơ — các con số trên chip tạm ẩn. Danh sách bên dưới vẫn đúng.
        </p>
      )}

      {isError && (
        <p
          role="alert"
          className="mt-4 rounded-lg border-2 border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700"
        >
          Không tải được danh sách ({String((error as Error)?.message)}). Vui lòng thử lại.
        </p>
      )}

      {/* "Đang hiện X trong Y" — thiếu dòng này thì một trang đầy trông y hệt "toàn bộ dữ liệu". */}
      {total != null && filtered.length > 0 && (
        <p className="mt-4 text-[13px] text-ink/65">
          Đang hiện{" "}
          <strong className="font-semibold text-ink">
            {offset + 1}–{offset + filtered.length}
          </strong>{" "}
          trong <strong className="font-semibold text-ink">{total}</strong> hồ sơ.
        </p>
      )}

      <div className="mt-4 overflow-hidden rounded-xl border-2 border-divider bg-canvas">
        {isLoading && <p className="px-4 py-6 text-sm text-ink/65">Đang tải danh sách…</p>}

        {/* Cổng `data &&`: khi fetch HỎNG thì `data` là undefined, và nếu không có cổng này màn hình
            in "Chưa có ứng viên nào" như một SỰ THẬT — ngay bên dưới một banner đỏ báo lỗi tải. Đó
            là "0 GIẢ" mà `(hr)/page.tsx` đã gọi đúng tên; trang này là chỗ duy nhất còn sót. */}
        {!isLoading && data && filtered.length === 0 && (
          <p className="px-6 py-10 text-center text-[13px] text-ink/65">
            {bucket === "all"
              ? "Chưa có ứng viên nào — nộp CV qua cổng tuyển dụng công khai để pipeline chạy."
              : "Không có ứng viên trong rổ này."}
          </p>
        )}

        {filtered.length > 0 && (
          <>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[640px] border-collapse text-sm">
                <thead>
                  <tr>
                    {["Ứng viên", "Vị trí", "Ngày nộp", "Điểm", "Trạng thái"].map((h, i) => (
                      <th
                        key={h}
                        className={`border-b-2 border-divider px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-ink/65 ${
                          i === 3 ? "text-right" : "text-left"
                        }`}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((a) => (
                    <tr key={a.id} className="border-b border-divider last:border-b-0 hover:bg-ink/[0.04]">
                      <td className="px-3 py-2">
                        <Link href={`/applications/${a.id}`} className="flex items-center gap-2.5">
                          <span className="flex h-[34px] w-[34px] flex-none items-center justify-center rounded-lg bg-steel-200 font-heading text-[13px] font-bold">
                            {initialsOf(a.applicant_email)}
                          </span>
                          <span className="min-w-0">
                            <span className="block truncate font-semibold">
                              {a.applicant_email.split("@")[0]}
                            </span>
                            <span className="block truncate text-xs text-ink/65">
                              {a.applicant_email}
                            </span>
                          </span>
                        </Link>
                      </td>
                      <td className="px-3 py-2 text-ink/75">
                        {a.job_id ? (jobTitle.get(a.job_id) ?? `JD #${a.job_id}`) : "—"}
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-[13px] text-ink/65">
                        {formatVnDateTime(a.created_at)}
                      </td>
                      <td className="px-3 py-2 text-right font-heading text-base font-bold">
                        {a.score != null ? a.score : "—"}
                      </td>
                      <td className="px-3 py-2">
                        <StatusCell a={a} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Điện thoại: bảng min-w-[640px] buộc cuộn ngang và đẩy cột Trạng thái ra ngoài tầm nhìn.
                Thẻ xếp dọc cho cả bốn thông tin cùng lúc. CẢ THẺ là link (bảng chỉ ô đầu là link, mà
                cả hàng lại đổi màu khi rê chuột — hứa một vùng bấm không tồn tại). */}
            <ul className="divide-y divide-divider md:hidden">
              {filtered.map((a) => (
                <li key={a.id}>
                  <Link
                    href={`/applications/${a.id}`}
                    className="flex flex-col gap-2 px-4 py-3 hover:bg-ink/[0.04]"
                  >
                    <div className="flex items-center gap-2.5">
                      <span className="flex h-[34px] w-[34px] flex-none items-center justify-center rounded-lg bg-steel-200 font-heading text-[13px] font-bold">
                        {initialsOf(a.applicant_email)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-semibold">
                          {a.applicant_email.split("@")[0]}
                        </span>
                        <span className="block truncate text-xs text-ink/65">{a.applicant_email}</span>
                      </span>
                      <span className="flex-none font-heading text-base font-bold">
                        {a.score != null ? a.score : "—"}
                      </span>
                    </div>
                    <p className="text-[13px] text-ink/75">
                      {a.job_id ? (jobTitle.get(a.job_id) ?? `JD #${a.job_id}`) : "—"}
                    </p>
                    <StatusCell a={a} />
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      {(hasMore || offset > 0) && (
        <div className="mt-4 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            disabled={offset === 0 || isLoading}
            className="rounded-lg border-2 border-divider px-4 py-2 text-[13px] font-semibold text-ink/70 transition-colors hover:bg-ink/[0.06] disabled:cursor-not-allowed disabled:opacity-40"
          >
            ← Trang trước
          </button>
          <span className="text-[13px] text-ink/65">
            Trang {Math.floor(offset / PAGE_SIZE) + 1}
            {total != null && ` / ${Math.max(1, Math.ceil(total / PAGE_SIZE))}`}
          </span>
          <button
            type="button"
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
            disabled={!hasMore || isLoading}
            className="rounded-lg border-2 border-divider px-4 py-2 text-[13px] font-semibold text-ink/70 transition-colors hover:bg-ink/[0.06] disabled:cursor-not-allowed disabled:opacity-40"
          >
            Trang sau →
          </button>
        </div>
      )}
    </div>
  );
}
