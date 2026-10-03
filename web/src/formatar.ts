/** Números do jeito brasileiro. */

export function duracao(segundos: number): string {
  if (!Number.isFinite(segundos)) return '—';
  const s = Math.round(segundos);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${String(s % 60).padStart(2, '0')} s`;
}

export function bytes(n: number): string {
  if (n < 1024 * 1024) return `${(n / 1024).toLocaleString('pt-BR', {maximumFractionDigits: 0})} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 / 1024).toLocaleString('pt-BR', {maximumFractionDigits: 1})} MB`;
  return `${(n / 1024 ** 3).toLocaleString('pt-BR', {maximumFractionDigits: 2})} GB`;
}

export function numero(n: number, casas = 0): string {
  return n.toLocaleString('pt-BR', {minimumFractionDigits: casas, maximumFractionDigits: casas});
}
