/** Human-readable byte sizes (binary units). Used for provider bandwidth counters. */
const UNITS = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"] as const;

export function formatBytes(bytes: number, fractionDigits = 1): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const exp = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), UNITS.length - 1);
  const value = bytes / 1024 ** exp;
  // Whole bytes never need decimals.
  const digits = exp === 0 ? 0 : fractionDigits;
  return `${value.toFixed(digits)} ${UNITS[exp]}`;
}
