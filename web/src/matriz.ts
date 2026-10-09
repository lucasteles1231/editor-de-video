/**
 * A matriz na página: o que o servidor devolve (listas ou texto com vírgulas, campos
 * faltando) vira linhas que a tabela de revisão edita, e as linhas viram o cenas.json.
 */
import type {CenaDaMatriz} from './tipos';

const texto = (v: unknown) => (typeof v === 'string' ? v : v == null ? '' : String(v));
const lista = (v: unknown) => (Array.isArray(v) ? v.map(texto).filter(Boolean).join(', ') : texto(v));

export function paraLinhas(cenas: Record<string, unknown>[]): CenaDaMatriz[] {
  return cenas.map((c) => ({
    id: texto(c.id), arquivo: texto(c.arquivo), descricao: texto(c.descricao), categorias: lista(c.categorias),
    personagens: lista(c.personagens), periodo: texto(c.periodo), energia: texto(c.energia),
    monetizacao: texto(c.monetizacao) || 'ok', obs: texto(c.obs),
    ...(typeof c.duracao === 'number' ? {duracao: c.duracao} : {}),
  }));
}

const separar = (v: string) => v.split(',').map((s) => s.trim()).filter(Boolean);

/** O cenas.json das linhas, no formato que o editor lê (as listas como listas). */
export function paraJson(linhas: CenaDaMatriz[]): string {
  return `${JSON.stringify(linhas.map((l) => ({
    ...(l.id ? {id: l.id} : {}), arquivo: l.arquivo, descricao: l.descricao.trim(),
    categorias: separar(l.categorias), personagens: separar(l.personagens), periodo: l.periodo,
    energia: l.energia, monetizacao: l.monetizacao, obs: l.obs.trim(),
    ...(l.duracao != null ? {duracao: l.duracao} : {}),
  })), null, 2)}\n`;
}
