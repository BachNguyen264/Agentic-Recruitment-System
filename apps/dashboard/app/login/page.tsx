"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { login } from "@/lib/api";

// Trang đăng nhập HR (slice 09, PRD §4). CÔNG KHAI (ngoài nhóm (hr)) — không bị guard. Đăng nhập
// thành công → về ?next (mặc định /). Lỗi → message CHUNG từ backend (không lộ email tồn tại).
function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const mutation = useMutation({
    mutationFn: () => login(email.trim(), password),
    onSuccess: () => {
      // next chỉ nhận đường dẫn nội bộ (chống open-redirect: phải bắt đầu bằng "/" và không "//").
      const safe = next.startsWith("/") && !next.startsWith("//") ? next : "/";
      // replace + full nav để layout (hr) chạy lại getMe với cookie mới.
      window.location.replace(safe);
    },
  });

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-6">
      <div className="space-y-6">
        <header className="space-y-1">
          <h1 className="text-2xl font-bold text-slate-900">Đăng nhập HR</h1>
          <p className="text-sm text-slate-500">
            Khu vực quản trị tuyển dụng. Chỉ dành cho HR — ứng viên nộp hồ sơ ở trang tuyển dụng công
            khai.
          </p>
        </header>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            mutation.mutate();
          }}
          className="space-y-4"
        >
          <div className="space-y-1">
            <label htmlFor="email" className="text-sm font-medium text-slate-700">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="password" className="text-sm font-medium text-slate-700">
              Mật khẩu
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
            />
          </div>

          {mutation.isError && (
            <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {String((mutation.error as Error)?.message) || "Đăng nhập thất bại."}
            </p>
          )}

          <button
            type="submit"
            disabled={mutation.isPending}
            className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 disabled:opacity-50"
          >
            {mutation.isPending ? "Đang đăng nhập…" : "Đăng nhập"}
          </button>
        </form>
      </div>
    </main>
  );
}

// useSearchParams cần Suspense boundary (Next 14 static export rule).
export default function LoginPage() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-slate-500">Đang tải…</div>}>
      <LoginForm />
    </Suspense>
  );
}
