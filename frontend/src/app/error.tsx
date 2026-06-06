"use client";

export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="empty">
      <p>Something went wrong.</p>
      <button className="btn" onClick={reset}>Try again</button>
    </div>
  );
}
