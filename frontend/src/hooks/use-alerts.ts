import { useCallback, useEffect, useState } from "react";
import type { AlertStatus } from "@/types";

const STORAGE_KEY = "anomaly-alert-statuses";

function readStoredStatuses() {
  if (typeof window === "undefined") return {};

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, AlertStatus>) : {};
  } catch {
    return {};
  }
}

export function useAlerts() {
  const [statuses, setStatuses] = useState<Record<string, AlertStatus>>(() => readStoredStatuses());

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(statuses));
    } catch {
      return;
    }
  }, [statuses]);

  const acknowledge = useCallback((id: string) => {
    setStatuses((prev) => ({ ...prev, [id]: "Acknowledged" }));
  }, []);

  const resolve = useCallback((id: string) => {
    setStatuses((prev) => ({ ...prev, [id]: "Resolved" }));
  }, []);

  const reopen = useCallback((id: string) => {
    setStatuses((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
  }, []);

  return { statuses, acknowledge, resolve, reopen };
}
