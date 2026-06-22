import { StatusBar } from "expo-status-bar";
import { useEffect, useState } from "react";
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from "react-native";
import type { HealthStatus } from "@ars/shared-types";

// Trên thiết bị thật, "localhost" trỏ về máy điện thoại — đặt EXPO_PUBLIC_API_BASE = IP LAN của backend.
const API_BASE = process.env.EXPO_PUBLIC_API_BASE ?? "http://localhost:8000";

function StatusRow({ label, state }: { label: string; state: string }) {
  const ok = state === "ok";
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      <View style={styles.rowRight}>
        <View style={[styles.dot, { backgroundColor: ok ? "#22c55e" : "#ef4444" }]} />
        <Text style={{ color: ok ? "#15803d" : "#b91c1c" }}>{state}</Text>
      </View>
    </View>
  );
}

export default function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const res = await fetch(`${API_BASE}/api/health`);
        const data = (await res.json()) as HealthStatus;
        if (active) {
          setHealth(data);
          setError(null);
        }
      } catch (e) {
        if (active) setError(String(e));
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    const id = setInterval(load, 5000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <StatusBar style="auto" />
      <Text style={styles.title}>ARS — HR Mobile</Text>
      <Text style={styles.subtitle}>Trạng thái backend (scaffold). Duyệt human_review — phase sau.</Text>

      {loading && <ActivityIndicator style={{ marginTop: 24 }} />}
      {error && <Text style={styles.error}>Không gọi được backend: {error}</Text>}

      {health && (
        <View style={styles.card}>
          <StatusRow label="API (FastAPI)" state={health.api} />
          <StatusRow label="Postgres (Neon)" state={health.services.postgres} />
          <StatusRow label="Redis (Upstash)" state={health.services.redis} />
          <StatusRow label="Qdrant Cloud" state={health.services.qdrant} />
          <Text style={styles.overall}>Tổng thể: {health.status}</Text>
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flexGrow: 1, backgroundColor: "#f8fafc", padding: 24, paddingTop: 64 },
  title: { fontSize: 22, fontWeight: "700", color: "#0f172a" },
  subtitle: { marginTop: 4, color: "#64748b" },
  card: { marginTop: 20, gap: 8 },
  row: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#ffffff",
    borderRadius: 8,
    borderWidth: 1,
    borderColor: "#e2e8f0",
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  rowLabel: { fontWeight: "600", color: "#0f172a" },
  rowRight: { flexDirection: "row", alignItems: "center", gap: 8 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  overall: { marginTop: 6, color: "#64748b" },
  error: { marginTop: 16, color: "#b91c1c" },
});
