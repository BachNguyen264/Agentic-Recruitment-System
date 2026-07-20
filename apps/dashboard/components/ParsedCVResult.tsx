import type { ParsedCV } from "@ars/shared-types";
import { Tag, type TagTone } from "@/components/ui";

// THUẦN presentational: nhận prop, KHÔNG tự fetch — tái dùng ở chi tiết ứng viên (HR) + /cv-check.
// Kiểu dáng bám thiết kế (ARS.dc.html 741–757): thẻ dữ liệu viền 2px, nhãn mục 13px/700, các mục
// dài (kinh nghiệm/học vấn) là HÀNG ngăn bằng đường kẻ trên — không phải thẻ lồng thẻ.
interface ParsedCVResultProps {
  parsed_data: ParsedCV | null;
  confidence: number;
  uncertainty_flags: string[];
  escalation_reason?: string | null;
  // Trang chi tiết ứng viên đã có ScoreBreakdown lo phần confidence/flags của Ranker — ẩn badge
  // confidence ở đây để khỏi nhầm tín hiệu Ranker thành chất lượng bóc tách (mặc định hiện, cho cv-check).
  showConfidence?: boolean;
}

function confidenceStyle(c: number): { label: string; tone: TagTone } {
  if (c >= 0.8) return { label: "Đầy đủ", tone: "ok" };
  if (c >= 0.5) return { label: "Một phần", tone: "warn" };
  return { label: "Thiếu nhiều", tone: "danger" };
}

// Nhãn của một mục (Kỹ năng / Kinh nghiệm / …) — 13px đậm, khớp thiết kế.
function SectionLabel({ children }: { children: React.ReactNode }) {
  return <h3 className="font-heading text-[13px] font-bold">{children}</h3>;
}

function Field({
  label,
  value,
  className = "",
}: {
  label: string;
  value: string | null | undefined;
  className?: string;
}) {
  const text = value?.toString().trim();
  return (
    // min-w-0 + break-words: ô lưới mặc định KHÔNG co dưới kích thước nội dung, nên một email dài
    // sẽ tràn sang ô bên cạnh (đè lên "Điện thoại") thay vì tự xuống dòng.
    <div className={`min-w-0 ${className}`}>
      <dt className="text-xs uppercase tracking-[0.06em] text-ink/45">{label}</dt>
      <dd className="break-words text-[13px] text-ink">{text ? text : "—"}</dd>
    </div>
  );
}

export function ParsedCVResult({
  parsed_data,
  confidence,
  uncertainty_flags,
  escalation_reason,
  showConfidence = true,
}: ParsedCVResultProps) {
  const conf = confidenceStyle(confidence);
  const failed = uncertainty_flags.includes("parse_failed");

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-1 text-[20px]">Kết quả bóc tách</h2>
        {showConfidence && (
          <>
            <Tag tone={conf.tone}>
              {conf.label} · conf {confidence.toFixed(2)}
            </Tag>
            {uncertainty_flags.map((flag) => (
              <Tag key={flag} tone="warn">
                {flag}
              </Tag>
            ))}
          </>
        )}
      </div>

      {failed ? (
        // parse_failed: cảnh báo rõ, KHÔNG cố render trường trống.
        <div className="rounded-xl border-2 border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-800">
          <p className="font-heading font-bold">Không đọc được CV</p>
          <p className="mt-1 leading-relaxed text-red-700">
            {escalation_reason ??
              "Có thể là ảnh scan hoặc định dạng không hỗ trợ — chưa trích được văn bản."}
          </p>
        </div>
      ) : parsed_data == null || Object.keys(parsed_data).length === 0 ? (
        // parsed_data có thể là {} (row scaffold/legacy chưa qua parser) — coi như chưa có dữ liệu.
        <p className="text-[13px] text-ink/55">Không có dữ liệu bóc tách.</p>
      ) : (
        <div className="space-y-4">
          {/* Liên hệ */}
          <div className="rounded-xl border-2 border-divider bg-canvas px-4 py-3.5">
            <p className="font-heading text-[17px] font-bold">
              {parsed_data.full_name?.trim() || "(Không rõ họ tên)"}
            </p>
            {/* Điện thoại + số năm KN NGẮN → chung một hàng; email DÀI → chiếm trọn hàng dưới.
                Cột chi tiết ứng viên chỉ rộng ~1fr nên chia đều 3 cột sẽ bóp email vỡ bố cục. */}
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2.5">
              <Field label="Điện thoại" value={parsed_data.phone} />
              <Field
                label="Tổng năm KN"
                value={
                  parsed_data.total_years_experience != null
                    ? String(parsed_data.total_years_experience)
                    : null
                }
              />
              <Field label="Email" value={parsed_data.email} className="col-span-2" />
            </dl>
          </div>

          {/* Tóm tắt nghề nghiệp */}
          {parsed_data.professional_summary?.trim() && (
            <div className="space-y-1.5">
              <SectionLabel>Tóm tắt</SectionLabel>
              <p className="text-[13px] leading-relaxed text-ink/80">
                {parsed_data.professional_summary}
              </p>
            </div>
          )}

          {/* Kỹ năng (?? [] — JSONB có thể thiếu trường ở row cũ/partial) */}
          {(parsed_data.skills ?? []).length > 0 && (
            <div className="space-y-2">
              <SectionLabel>Kỹ năng ({parsed_data.skills.length})</SectionLabel>
              <div className="flex flex-wrap gap-1.5">
                {parsed_data.skills.map((s, i) => (
                  <Tag key={`${s}-${i}`} tone="neutral">
                    {s}
                  </Tag>
                ))}
              </div>
            </div>
          )}

          {/* Kinh nghiệm — HÀNG ngăn bằng đường kẻ trên (thiết kế), không lồng thẻ trong thẻ */}
          {(parsed_data.experiences ?? []).length > 0 && (
            <div className="space-y-1">
              <SectionLabel>Kinh nghiệm ({parsed_data.experiences.length})</SectionLabel>
              <ol>
                {parsed_data.experiences.map((exp, i) => (
                  <li key={i} className="border-t border-divider py-2">
                    <div className="flex flex-wrap items-baseline gap-x-1.5">
                      <span className="text-[13px] font-semibold">
                        {exp.title?.trim() || "(Vị trí không rõ)"}
                      </span>
                      <span className="text-[13px] text-ink/60">
                        {exp.company?.trim() || "Dự án cá nhân"}
                      </span>
                    </div>
                    {exp.duration?.trim() && (
                      <p className="text-xs text-ink/45">{exp.duration}</p>
                    )}
                    {exp.summary?.trim() && (
                      <p className="mt-1 text-[13px] leading-relaxed text-ink/70">{exp.summary}</p>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Học vấn */}
          {(parsed_data.education ?? []).length > 0 && (
            <div className="space-y-1">
              <SectionLabel>Học vấn ({parsed_data.education.length})</SectionLabel>
              <ol>
                {parsed_data.education.map((edu, i) => (
                  <li key={i} className="border-t border-divider py-2">
                    <div className="text-[13px] font-semibold">
                      {edu.school?.trim() || "(Trường không rõ)"}
                    </div>
                    <div className="flex flex-wrap gap-x-1.5 text-xs text-ink/50">
                      {edu.field?.trim() && <span>{edu.field}</span>}
                      {edu.degree?.trim() && <span>· {edu.degree}</span>}
                      {edu.year?.trim() && <span>· {edu.year}</span>}
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Chứng chỉ (?? [] — tương thích parsed_data cũ thiếu trường) */}
          {(parsed_data.certificates ?? []).length > 0 && (
            <div className="space-y-2">
              <SectionLabel>Chứng chỉ ({parsed_data.certificates.length})</SectionLabel>
              <div className="flex flex-wrap gap-1.5">
                {parsed_data.certificates.map((c, i) => (
                  <Tag key={`${c.name}-${i}`} tone="neutral">
                    {c.name}
                    {c.detail?.trim() ? ` · ${c.detail}` : ""}
                    {c.year?.trim() ? ` (${c.year})` : ""}
                  </Tag>
                ))}
              </div>
            </div>
          )}

          {/* Ngôn ngữ */}
          {(parsed_data.languages ?? []).length > 0 && (
            <div className="space-y-2">
              <SectionLabel>Ngôn ngữ ({parsed_data.languages.length})</SectionLabel>
              <div className="flex flex-wrap gap-1.5">
                {parsed_data.languages.map((l, i) => (
                  <Tag key={`${l.name}-${i}`} tone="neutral">
                    {l.name}
                    {l.proficiency?.trim() ? ` · ${l.proficiency}` : ""}
                  </Tag>
                ))}
              </div>
            </div>
          )}

          {/* Giải thưởng */}
          {(parsed_data.awards ?? []).length > 0 && (
            <div className="space-y-1.5">
              <SectionLabel>Giải thưởng ({parsed_data.awards.length})</SectionLabel>
              <ul className="list-disc space-y-1 pl-5 text-[13px] leading-relaxed text-ink/80">
                {parsed_data.awards.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Khác (lưới an toàn) */}
          {(parsed_data.other ?? []).length > 0 && (
            <div className="space-y-1">
              <SectionLabel>Khác ({parsed_data.other.length})</SectionLabel>
              <dl>
                {parsed_data.other.map((o, i) => (
                  <div key={i} className="border-t border-divider py-2">
                    <dt className="text-[13px] font-semibold">{o.label}</dt>
                    <dd className="text-[13px] leading-relaxed text-ink/70">{o.content}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
