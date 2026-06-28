"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function AdminLoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined" && localStorage.getItem("admin_token")) {
      router.replace("/admin/dashboard");
    }
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/api/admin/login`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password }),
        }
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail ?? "Invalid credentials");
        return;
      }
      const { token } = await res.json();
      localStorage.setItem("admin_token", token);
      router.push("/admin/dashboard");
    } catch {
      setError("Could not reach the server. Is the backend running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="admin-screen flex min-h-screen items-center justify-center px-4 py-8">
      <div className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 inline-flex h-12 w-12 items-center justify-center rounded-lg bg-slate-900">
            <svg className="h-6 w-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"
              />
            </svg>
          </div>
          <h1 className="text-2xl font-semibold text-slate-950">Admin Portal</h1>
          <p className="mt-1 text-sm text-slate-500">Manage forms, prompts, knowledgebase, and sessions.</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-600">
              Username
            </label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoComplete="username"
              className="w-full border border-slate-300 px-4 text-slate-950 placeholder-slate-400 outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
              placeholder="Enter username"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-600">
              Password
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              className="w-full border border-slate-300 px-4 text-slate-950 placeholder-slate-400 outline-none focus:border-slate-900 focus:ring-2 focus:ring-slate-200"
              placeholder="Enter password"
            />
          </div>

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="mt-2 w-full rounded-lg bg-slate-900 px-4 text-base font-semibold text-white transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
