"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ConfigField, ConfigGroup, ConfigValue } from "@ars/shared-types";
import { btn, Field, inputClass, Tag } from "@/components/ui";
import {
  BLANK_LABEL,
  configDefaultLabel,
  configText,
  getAdminConfig,
  resetAdminConfig,
  saveAdminConfig,
} from "@/lib/admin";

// Tab 1 — Cấu hình chạy được (PRD §NFR-8). Form được DỰNG TỪ metadata của backend
// (`core/config_registry.py`): nhãn, giải thích, kiểu, ràng buộc, đơn vị, cảnh báo đều do server
// khai. Chép một danh sách field sang đây là tự tạo nguồn chân lý thứ hai — thêm một ô ở backend
// mà quên thêm ở đây thì HR không bao giờ chỉnh được nó.

/** Ô nhập của MỘT field. Kiểu quyết định phần tử: enum → select, int/float → number, str → text. */
function ConfigInput({
  f,
  id,
  describedBy,
  text,
  onChange,
}: {
  f: ConfigField;
  id: string;
  describedBy: string;
  text: string;
  onChange: (next: string) => void;
}) {
  if (f.kind === "enum") {
    const choices = f.choices ?? [];
    // Field `nullable` mà danh sách lựa chọn KHÔNG có mục rỗng thì không có cách nào để trống được
    // qua giao diện — thêm mục rỗng vào đầu. (`_EFFORT` của backend vốn đã có "".)
    const options = f.nullable && !choices.includes("") ? ["", ...choices] : choices;
    return (
      <select
        id={id}
        aria-describedby={describedBy}
        className={inputClass}
        value={text}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((c) => (
          <option key={c} value={c}>
            {c === "" ? BLANK_LABEL : c}
          </option>
        ))}
      </select>
    );
  }

  if (f.kind === "int" || f.kind === "float") {
    return (
      <input
        id={id}
        type="number"
        aria-describedby={describedBy}
        className={inputClass}
        // `step` là gợi ý cho nút tăng/giảm + validate của trình duyệt. Số nguyên bước 1; số thực
        // "any" vì các ngưỡng ở đây có ô bước 0.05 (confidence) và ô bước 1 (giờ) — ép một bước cố
        // định sẽ làm trình duyệt báo "giá trị không hợp lệ" cho một con số backend chấp nhận.
        step={f.kind === "int" ? 1 : "any"}
        min={f.minimum ?? undefined}
        max={f.maximum ?? undefined}
        value={text}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  return (
    <input
      id={id}
      type="text"
      aria-describedby={describedBy}
      className={inputClass}
      value={text}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function ConfigRow({
  f,
  text,
  dirty,
  onChange,
  onReset,
  resetting,
}: {
  f: ConfigField;
  text: string;
  dirty: boolean;
  onChange: (next: string) => void;
  onReset: () => void;
  resetting: boolean;
}) {
  const id = `cfg-${f.key}`;
  const descId = `${id}-desc`;
  const unitId = `${id}-unit`;
  const warnId = `${id}-warn`;
  // Giải thích + đơn vị + cảnh báo nối vào ô nhập bằng `aria-describedby`, KHÔNG phải `title`:
  // tooltip theo kiểu hover chuột thì bàn phím không mở được và trình đọc màn hình bỏ qua — người
  // dùng chỉ còn cái nhãn trơ, trong khi phần giải thích mới là thứ nói cho họ biết nên đặt số nào.
  const describedBy = [descId, f.unit ? unitId : null, f.warning ? warnId : null]
    .filter(Boolean)
    .join(" ");

  return (
    <Field label={f.label} htmlFor={id}>
      <p id={descId} className="mb-2 text-xs leading-relaxed text-ink/65">
        {f.tooltip}
      </p>

      <div className="flex items-center gap-2">
        <ConfigInput f={f} id={id} describedBy={describedBy} text={text} onChange={onChange} />
        {f.unit && (
          <span id={unitId} className="flex-none text-[13px] text-ink/65">
            {f.unit}
          </span>
        )}
      </div>

      {/* CẢNH BÁO, không phải lỗi: giá trị vẫn hợp lệ với backend — nền/viền vàng chứ không đỏ. */}
      {f.warning && (
        <p
          id={warnId}
          className="mt-2 rounded-lg border-2 border-amber-300 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900"
        >
          {f.warning}
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-ink/65">
        <span>mặc định: {configDefaultLabel(f.default)}</span>
        {f.is_overridden && <Tag tone="accent">đã chỉnh</Tag>}
        {dirty && <Tag tone="warn">chưa lưu</Tag>}
        {f.is_overridden && (
          <button type="button" onClick={onReset} disabled={resetting} className={btn("ghost")}>
            {resetting ? "Đang khôi phục…" : "Khôi phục mặc định"}
          </button>
        )}
      </div>
    </Field>
  );
}

export function ConfigTab({ active }: { active: boolean }) {
  const qc = useQueryClient();
  // Bản nháp chỉ chứa những ô ĐÃ CHẠM. Giá trị là CHUỖI (dạng của <input>) và cũng là dạng gửi đi —
  // xem `configText` ở lib/admin để biết vì sao không ép kiểu ở client.
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);

  const { data, isLoading, isError, error } = useQuery<ConfigGroup[]>({
    queryKey: ["admin", "config"],
    queryFn: getAdminConfig,
    enabled: active,
  });

  const groups = data ?? [];
  // "Đã đổi" = có trong nháp VÀ khác giá trị đang chạy. Gõ vào rồi gõ trả lại như cũ thì KHÔNG tính
  // là đổi — nếu tính, nút Lưu sẽ sáng lên đòi ghi một thứ y hệt thứ đang có.
  const dirtyFields = groups
    .flatMap((g) => g.fields)
    .filter((f) => draft[f.key] !== undefined && draft[f.key] !== configText(f.value));

  const clearMessages = () => {
    setErrorMsg(null);
    setOkMsg(null);
  };

  const saveMutation = useMutation({
    mutationFn: (values: Record<string, ConfigValue>) => saveAdminConfig(values),
    onMutate: clearMessages,
    onSuccess: async (res) => {
      setDraft({}); // nháp đã thành sự thật ⇒ bỏ đi, để form đọc lại từ server.
      await qc.invalidateQueries({ queryKey: ["admin", "config"] });
      setOkMsg(
        res.changed.length > 0
          ? `Đã lưu ${res.changed.length} mục.`
          : "Đã lưu, nhưng không mục nào đổi giá trị (trùng giá trị đang chạy).",
      );
    },
    // Nguyên văn message của backend: 422 ở đây là câu tiếng Việt nói rõ ô nào sai và vì sao.
    // Nuốt nó thành "Có lỗi xảy ra" là lấy đi thứ duy nhất giúp HR sửa được.
    onError: (err) => setErrorMsg(String((err as Error)?.message) || "Không lưu được cấu hình."),
  });

  const resetMutation = useMutation({
    mutationFn: (key: string) => resetAdminConfig(key),
    onMutate: clearMessages,
    onSuccess: async (res, key) => {
      // Bỏ nháp của RIÊNG ô vừa khôi phục — giữ lại thì ô đó hiện số cũ đè lên mặc định vừa lấy về.
      setDraft((d) => {
        const next = { ...d };
        delete next[key];
        return next;
      });
      await qc.invalidateQueries({ queryKey: ["admin", "config"] });
      setOkMsg(
        res.changed.length > 0
          ? "Đã khôi phục giá trị mặc định."
          : "Ô này vốn đã bằng giá trị mặc định.",
      );
    },
    onError: (err) => setErrorMsg(String((err as Error)?.message) || "Không khôi phục được."),
  });

  const resettingKey = resetMutation.isPending ? resetMutation.variables : null;

  return (
    <div>
      {isLoading && <p className="text-sm text-ink/65">Đang tải cấu hình…</p>}

      {isError && (
        <p
          role="alert"
          className="rounded-lg border-2 border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700"
        >
          Không tải được cấu hình ({String((error as Error)?.message)}).
        </p>
      )}

      {/* Thứ tự nhóm và thứ tự ô trong nhóm GIỮ NGUYÊN như server trả về — `GROUP_ORDER` của backend
          đã sắp theo mức độ ảnh hưởng nghiệp vụ, sắp lại ở đây là bỏ đi thông tin đó. */}
      <div className="space-y-6">
        {groups.map((g) => (
          <section key={g.group}>
            <h2 className="text-[19px]">{g.group}</h2>
            <div className="mt-3 grid gap-5 rounded-xl border-2 border-divider bg-canvas p-4 md:grid-cols-2">
              {g.fields.map((f) => (
                <ConfigRow
                  key={f.key}
                  f={f}
                  text={draft[f.key] ?? configText(f.value)}
                  dirty={draft[f.key] !== undefined && draft[f.key] !== configText(f.value)}
                  onChange={(next) => setDraft((d) => ({ ...d, [f.key]: next }))}
                  onReset={() => resetMutation.mutate(f.key)}
                  resetting={resettingKey === f.key}
                />
              ))}
            </div>
          </section>
        ))}
      </div>

      {/* Thanh hành động DÍNH ĐÁY: form dài 39 ô, nút Lưu nằm cuối trang thì HR phải cuộn hết mới
          bấm được — và quan trọng hơn, thông báo lỗi 422 phải hiện ở nơi họ ĐANG NHÌN lúc bấm. */}
      {groups.length > 0 && (
        <div className="sticky bottom-0 mt-6 rounded-xl border-2 border-divider bg-surface px-4 py-3">
          {errorMsg && (
            <p
              role="alert"
              className="mb-2.5 rounded-lg border-2 border-red-200 bg-red-50 px-3 py-2 text-[13px] text-red-700"
            >
              {errorMsg}
            </p>
          )}
          {okMsg && (
            <p
              role="status"
              className="mb-2.5 rounded-lg border-2 border-ink bg-canvas px-3 py-2 text-[13px]"
            >
              {okMsg}
            </p>
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-[13px] text-ink/65">
              {dirtyFields.length === 0
                ? "Chưa có thay đổi nào."
                : `${dirtyFields.length} ô đã đổi, chưa lưu.`}
            </p>
            <button
              type="button"
              className={btn("primary")}
              // Chặn cả hai đường bấm thừa: không có gì để lưu, và bấm lần hai lúc lượt đầu đang bay.
              disabled={dirtyFields.length === 0 || saveMutation.isPending}
              onClick={() =>
                saveMutation.mutate(
                  // Ép tuple: thiếu nó `Object.fromEntries` rơi về overload `readonly any[]` và trả
                  // `any` — CLAUDE.md cấm `any` lỏng, và ở đây nó nuốt luôn việc kiểm kiểu payload.
                  Object.fromEntries(
                    dirtyFields.map((f): [string, ConfigValue] => [f.key, draft[f.key]]),
                  ),
                )
              }
            >
              {saveMutation.isPending ? "Đang lưu…" : "Lưu thay đổi"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
