import type { ParsedCV } from "@ars/shared-types";

// THUẦN presentational: nhận prop, KHÔNG tự fetch — tái dùng ở chi tiết ứng viên (HR) + trang nộp CV.
interface ParsedCVResultProps {
  parsed_data: ParsedCV | null;
  confidence: number;
  uncertainty_flags: string[];
  escalation_reason?: string | null;
  // Trang chi tiết ứng viên đã có ScoreBreakdown lo phần confidence/flags của Ranker — ẩn badge
  // confidence ở đây để khỏi nhầm tín hiệu Ranker thành chất lượng bóc tách (mặc định hiện, cho cv-check).
  showConfidence?: boolean;
}

function confidenceStyle(c: number): { label: string; cls: string } {
  if (c >= 0.8) return { label: "Đầy đủ", cls: "bg-green-100 text-green-800" };
  if (c >= 0.5) return { label: "Một phần", cls: "bg-amber-100 text-amber-800" };
  return { label: "Thiếu nhiều", cls: "bg-red-100 text-red-800" };
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded bg-steel-100 px-2 py-0.5 text-sm text-ink/80">{children}</span>
  );
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
      <dt className="text-xs uppercase tracking-wide text-ink/45">{label}</dt>
      <dd className="break-words text-sm text-ink">{text ? text : "—"}</dd>
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
        <h2 className="mr-1 text-lg font-semibold">Kết quả bóc tách</h2>
        {showConfidence && (
          <>
            <span className={`rounded px-2 py-0.5 text-sm font-medium ${conf.cls}`}>
              {conf.label} · conf {confidence.toFixed(2)}
            </span>
            {uncertainty_flags.map((flag) => (
              <span
                key={flag}
                className="rounded bg-amber-100 px-2 py-0.5 text-sm font-medium text-amber-800"
              >
                {flag}
              </span>
            ))}
          </>
        )}
      </div>

      {failed ? (
        // parse_failed: cảnh báo rõ, KHÔNG cố render trường trống.
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <p className="font-medium">Không đọc được CV</p>
          <p className="mt-1 text-red-700">
            {escalation_reason ??
              "Có thể là ảnh scan hoặc định dạng không hỗ trợ — chưa trích được văn bản."}
          </p>
        </div>
      ) : parsed_data == null || Object.keys(parsed_data).length === 0 ? (
        // parsed_data có thể là {} (row scaffold/legacy chưa qua parser) — coi như chưa có dữ liệu.
        <p className="text-sm text-ink/55">Không có dữ liệu bóc tách.</p>
      ) : (
        <div className="space-y-4">
          {/* Liên hệ */}
          <div className="rounded-lg border border-divider bg-canvas px-4 py-3">
            <p className="text-base font-semibold text-ink">
              {parsed_data.full_name?.trim() || "(Không rõ họ tên)"}
            </p>
            {/* Điện thoại + số năm KN NGẮN → xếp chung một hàng; email DÀI → chiếm trọn hàng dưới.
                Cột chi tiết ứng viên chỉ rộng ~1fr nên chia đều 3 cột sẽ bóp email vỡ bố cục. */}
            <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2">
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
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-ink/80">Tóm tắt</h3>
              <p className="text-sm leading-relaxed text-ink/80">
                {parsed_data.professional_summary}
              </p>
            </div>
          )}

          {/* Kỹ năng (?? [] — JSONB có thể thiếu trường ở row cũ/partial) */}
          {(parsed_data.skills ?? []).length > 0 && (
            <div className="space-y-1.5">
              <h3 className="text-sm font-semibold text-ink/80">
                Kỹ năng ({parsed_data.skills.length})
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {parsed_data.skills.map((s, i) => (
                  <Chip key={`${s}-${i}`}>{s}</Chip>
                ))}
              </div>
            </div>
          )}

          {/* Kinh nghiệm */}
          {(parsed_data.experiences ?? []).length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-ink/80">
                Kinh nghiệm ({parsed_data.experiences.length})
              </h3>
              <ol className="space-y-2">
                {parsed_data.experiences.map((exp, i) => (
                  <li
                    key={i}
                    className="rounded-lg border border-divider bg-canvas px-4 py-3 text-sm"
                  >
                    <div className="flex flex-wrap items-baseline gap-x-2">
                      <span className="font-medium text-ink">
                        {exp.title?.trim() || "(Vị trí không rõ)"}
                      </span>
                      <span className="text-ink/55">
                        {exp.company?.trim() || "Dự án cá nhân"}
                      </span>
                      {exp.duration?.trim() && (
                        <span className="text-ink/45">· {exp.duration}</span>
                      )}
                    </div>
                    {exp.summary?.trim() && (
                      <p className="mt-1 text-ink/65">{exp.summary}</p>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Học vấn */}
          {(parsed_data.education ?? []).length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-ink/80">
                Học vấn ({parsed_data.education.length})
              </h3>
              <ol className="space-y-2">
                {parsed_data.education.map((edu, i) => (
                  <li
                    key={i}
                    className="rounded-lg border border-divider bg-canvas px-4 py-3 text-sm"
                  >
                    <div className="font-medium text-ink">
                      {edu.school?.trim() || "(Trường không rõ)"}
                    </div>
                    <div className="mt-0.5 flex flex-wrap gap-x-2 text-ink/55">
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
            <div className="space-y-1.5">
              <h3 className="text-sm font-semibold text-ink/80">
                Chứng chỉ ({parsed_data.certificates.length})
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {parsed_data.certificates.map((c, i) => (
                  <Chip key={`${c.name}-${i}`}>
                    {c.name}
                    {c.detail?.trim() ? ` · ${c.detail}` : ""}
                    {c.year?.trim() ? ` (${c.year})` : ""}
                  </Chip>
                ))}
              </div>
            </div>
          )}

          {/* Ngôn ngữ */}
          {(parsed_data.languages ?? []).length > 0 && (
            <div className="space-y-1.5">
              <h3 className="text-sm font-semibold text-ink/80">
                Ngôn ngữ ({parsed_data.languages.length})
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {parsed_data.languages.map((l, i) => (
                  <Chip key={`${l.name}-${i}`}>
                    {l.name}
                    {l.proficiency?.trim() ? ` · ${l.proficiency}` : ""}
                  </Chip>
                ))}
              </div>
            </div>
          )}

          {/* Giải thưởng */}
          {(parsed_data.awards ?? []).length > 0 && (
            <div className="space-y-1.5">
              <h3 className="text-sm font-semibold text-ink/80">
                Giải thưởng ({parsed_data.awards.length})
              </h3>
              <ul className="list-disc space-y-0.5 pl-5 text-sm text-ink/80">
                {parsed_data.awards.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Khác (lưới an toàn) */}
          {(parsed_data.other ?? []).length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-ink/80">
                Khác ({parsed_data.other.length})
              </h3>
              <dl className="space-y-1">
                {parsed_data.other.map((o, i) => (
                  <div key={i} className="text-sm">
                    <dt className="font-medium text-ink/80">{o.label}</dt>
                    <dd className="text-ink/65">{o.content}</dd>
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
