import type { ParsedCV } from "@ars/shared-types";

// THUẦN presentational: nhận prop, KHÔNG tự fetch — tái dùng ở chi tiết ứng viên (HR) + trang nộp CV.
interface ParsedCVResultProps {
  parsed_data: ParsedCV | null;
  confidence: number;
  uncertainty_flags: string[];
  escalation_reason?: string | null;
}

function confidenceStyle(c: number): { label: string; cls: string } {
  if (c >= 0.8) return { label: "Đầy đủ", cls: "bg-green-100 text-green-800" };
  if (c >= 0.5) return { label: "Một phần", cls: "bg-amber-100 text-amber-800" };
  return { label: "Thiếu nhiều", cls: "bg-red-100 text-red-800" };
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded bg-slate-100 px-2 py-0.5 text-sm text-slate-700">{children}</span>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  const text = value?.toString().trim();
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="text-sm text-slate-800">{text ? text : "—"}</dd>
    </div>
  );
}

export function ParsedCVResult({
  parsed_data,
  confidence,
  uncertainty_flags,
  escalation_reason,
}: ParsedCVResultProps) {
  const conf = confidenceStyle(confidence);
  const failed = uncertainty_flags.includes("parse_failed");

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-1 text-lg font-semibold">Kết quả bóc tách</h2>
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
      </div>

      {failed ? (
        // parse_failed: cảnh báo rõ, KHÔNG cố render trường trống.
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <p className="font-medium">Không đọc được CV</p>
          <p className="mt-1 text-red-700">
            {escalation_reason ??
              "Có thể là ảnh scan hoặc định dạng không hỗ trợ — chưa trích được văn bản."}
          </p>
        </div>
      ) : parsed_data == null ? (
        <p className="text-sm text-slate-500">Không có dữ liệu bóc tách.</p>
      ) : (
        <div className="space-y-4">
          {/* Liên hệ */}
          <div className="rounded-md border border-slate-200 bg-white px-4 py-3">
            <p className="text-base font-semibold text-slate-900">
              {parsed_data.full_name?.trim() || "(Không rõ họ tên)"}
            </p>
            <dl className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
              <Field label="Email" value={parsed_data.email} />
              <Field label="Điện thoại" value={parsed_data.phone} />
              <Field
                label="Tổng năm KN"
                value={
                  parsed_data.total_years_experience != null
                    ? String(parsed_data.total_years_experience)
                    : null
                }
              />
            </dl>
          </div>

          {/* Tóm tắt nghề nghiệp */}
          {parsed_data.professional_summary?.trim() && (
            <div className="space-y-1">
              <h3 className="text-sm font-semibold text-slate-700">Tóm tắt</h3>
              <p className="text-sm leading-relaxed text-slate-700">
                {parsed_data.professional_summary}
              </p>
            </div>
          )}

          {/* Kỹ năng */}
          {parsed_data.skills.length > 0 && (
            <div className="space-y-1.5">
              <h3 className="text-sm font-semibold text-slate-700">
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
          {parsed_data.experiences.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-slate-700">
                Kinh nghiệm ({parsed_data.experiences.length})
              </h3>
              <ol className="space-y-2">
                {parsed_data.experiences.map((exp, i) => (
                  <li
                    key={i}
                    className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm"
                  >
                    <div className="flex flex-wrap items-baseline gap-x-2">
                      <span className="font-medium text-slate-900">
                        {exp.title?.trim() || "(Vị trí không rõ)"}
                      </span>
                      <span className="text-slate-500">
                        {exp.company?.trim() || "Dự án cá nhân"}
                      </span>
                      {exp.duration?.trim() && (
                        <span className="text-slate-400">· {exp.duration}</span>
                      )}
                    </div>
                    {exp.summary?.trim() && (
                      <p className="mt-1 text-slate-600">{exp.summary}</p>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {/* Học vấn */}
          {parsed_data.education.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-semibold text-slate-700">
                Học vấn ({parsed_data.education.length})
              </h3>
              <ol className="space-y-2">
                {parsed_data.education.map((edu, i) => (
                  <li
                    key={i}
                    className="rounded-md border border-slate-200 bg-white px-4 py-3 text-sm"
                  >
                    <div className="font-medium text-slate-900">
                      {edu.school?.trim() || "(Trường không rõ)"}
                    </div>
                    <div className="mt-0.5 flex flex-wrap gap-x-2 text-slate-500">
                      {edu.field?.trim() && <span>{edu.field}</span>}
                      {edu.degree?.trim() && <span>· {edu.degree}</span>}
                      {edu.year?.trim() && <span>· {edu.year}</span>}
                    </div>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
