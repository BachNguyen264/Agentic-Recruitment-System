"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Logo } from "@/components/Logo";
import { btn, Field, inputClass } from "@/components/ui";
import { login } from "@/lib/api";

// Trang đăng nhập HR (slice 09, PRD §4). CÔNG KHAI (ngoài nhóm (hr)) — không bị guard.
// MỘT vai HR-admin duy nhất: KHÔNG đăng ký, KHÔNG quên mật khẩu, KHÔNG OAuth (đừng thêm link nào
// như vậy). Lỗi đăng nhập dùng message CHUNG từ backend — không lộ email nào tồn tại.
function LoginForm() {
  const params = useSearchParams();
  const next = params.get("next") || "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const mutation = useMutation({
    mutationFn: () => login(email.trim(), password),
    onSuccess: () => {
      // next CHỈ nhận đường dẫn nội bộ (chống open-redirect: phải bắt đầu "/" và không "//").
      const safe = next.startsWith("/") && !next.startsWith("//") ? next : "/";
      // replace + điều hướng đầy đủ để layout (hr) chạy lại getMe với cookie mới.
      window.location.replace(safe);
    },
  });

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-5 py-10">
      <div className="w-full max-w-[360px]">
        <Logo size={30} />

        <h1 className="mt-6 text-[26px] sm:text-[30px]">Đăng nhập HR</h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-ink/55">
          Khu vực quản trị tuyển dụng. Ứng viên nộp hồ sơ ở cổng công khai — không cần tài khoản.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate();
          }}
          className="mt-5 flex flex-col gap-3.5"
        >
          <Field label="Email" htmlFor="login-email">
            <input
              id="login-email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={mutation.isPending}
              className={inputClass}
            />
          </Field>

          <Field label="Mật khẩu" htmlFor="login-password">
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={mutation.isPending}
              className={inputClass}
            />
          </Field>

          {mutation.isError && (
            <p
              role="alert"
              className="rounded-xl border-2 border-red-200 bg-red-50 px-4 py-2.5 text-[13px] text-red-700"
            >
              {String((mutation.error as Error)?.message) || "Đăng nhập thất bại."}
            </p>
          )}

          <button
            type="submit"
            disabled={mutation.isPending}
            className={btn("primary", "mt-1 w-full !py-2.5")}
          >
            {mutation.isPending ? "Đang đăng nhập…" : "Đăng nhập"}
          </button>
        </form>
      </div>
    </main>
  );
}

// useSearchParams cần Suspense boundary (quy tắc Next 14).
export default function LoginPage() {
  return (
    <Suspense
      fallback={<div className="p-8 text-[13px] text-ink/50">Đang tải…</div>}
    >
      <LoginForm />
    </Suspense>
  );
}
