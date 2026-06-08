import { useCallback, useEffect, useState } from "react";
import type { AlertStatus } from "@/types";

const STORAGE_KEY = "anomaly-alert-statuses";

export function useAlerts() {
  const [statuses, setStatuses] = useState<Record<string, AlertStatus>>({});
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) setStatuses(JSON.parse(raw) as Record<string, AlertStatus>);
    } catch {}
    setLoaded(true);
  }, []);

  useEffect(() => {
    if (!loaded) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(statuses));
    } catch {}
  }, [statuses, loaded]);

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
