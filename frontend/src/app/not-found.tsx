import Link from "next/link";

export default function NotFound() {
  return (
    <div className="empty">
      <p>Page not found.</p>
      <Link className="btn" href="/dashboard">Back to dashboard</Link>
    </div>
  );
}
