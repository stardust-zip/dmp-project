import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "anomaly-assignments";

function readStoredAssignments(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, string>) : {};
  } catch {
    return {};
  }
}

export function useAssignments() {
  const [assignments, setAssignments] = useState<Record<string, string>>(() => readStoredAssignments());

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(assignments));
    } catch {
      return;
    }
  }, [assignments]);

  const assign = useCallback((eventId: string, userId: string | null) => {
    setAssignments((prev) => {
      const next = { ...prev };
      if (userId === null) {
        delete next[eventId];
      } else {
        next[eventId] = userId;
      }
      return next;
    });
  }, []);

  return { assignments, assign };
}
