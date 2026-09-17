export function StatusBadge({ label, tone = 'neutral' }: { label: string; tone?: 'neutral' | 'success' | 'warning' | 'danger' }) {
  return <span className={`status-badge ${tone}`}>{label}</span>;
}
