"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import type { AgentTraceStep, RunDemoResponse } from "@ars/shared-types";
import { postJson } from "@/lib/api";

function TraceRow({ step }: { step: AgentTraceStep }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm">
      <span className="font-mono font-semibold">{step.node}</span>
      <span className="text-slate-500">{step.status ?? "—"}</span>
      {step.confidence != null && (
        <span className="text-slate-600">conf={step.confidence.toFixed(2)}</span>
      )}
      {step.uncertainty_flags.length > 0 && (
        <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-800">
          {step.uncertainty_flags.join(", ")}
        </span>
      )}
      {step.require_human_review && (
        <span className="rounded bg-red-100 px-1.5 py-0.5 text-red-700">human_review</span>
      )}
    </li>
  );
}

export function AgentTracePanel() {
  const [forceReview, setForceReview] = useState(false);
  const mutation = useMutation({
    mutationFn: (fr: boolean) =>
      postJson<RunDemoResponse>("/api/agents/run-demo", { force_review: fr }),
  });
  const result = mutation.data;

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold">Agent trace (demo pipeline)</h2>

      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={forceReview}
            onChange={(e) => setForceReview(e.target.checked)}
          />
          Ép nhánh <span className="font-mono">human_review</span> (ca bất định)
        </label>
        <button
          onClick={() => mutation.mutate(forceReview)}
          disabled={mutation.isPending}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
        >
          {mutation.isPending ? "Đang chạy…" : "Run demo"}
        </button>
      </div>

      {mutation.isError && (
        <p className="text-sm text-red-600">
          Lỗi: {String((mutation.error as Error)?.message)} (backend :8000 đã chạy chưa?)
        </p>
      )}

      {result && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span
              className={`rounded px-2 py-0.5 font-medium ${
                result.branch === "auto"
                  ? "bg-green-100 text-green-800"
                  : "bg-red-100 text-red-800"
              }`}
            >
              branch: {result.branch}
            </span>
            <span>
              final: <span className="font-medium">{result.final_status}</span>
            </span>
            {result.escalation_reason && (
              <span className="text-slate-500">lý do: {result.escalation_reason}</span>
            )}
          </div>
          <ol className="space-y-1.5">
            {result.trace.map((step, i) => (
              <TraceRow key={i} step={step} />
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
