"use client";

import { Spinner } from "@/components/common/primitives";

export default function Loading() {
  return (
    <div className="empty" style={{ height: "100%", minHeight: 320 }}>
      <Spinner size={22} />
    </div>
  );
}
