import assert from "node:assert/strict";
import test from "node:test";
import { posicionarPalavras } from "./nuvemPublicidade.ts";

const palavras = Array.from({ length: 36 }, (_, i) => ({ categoria: `Categoria eleitoral ${i}`, grupo: `Tipo ${i % 8}`, valor: 10000 / (i + 1) }));

for (const [largura, altura] of [[820, 450], [340, 420]]) {
  test(`nuvem ${largura}px não sobrepõe rótulos nem ultrapassa limites`, () => {
    const result = posicionarPalavras(palavras, largura, altura);
    assert.ok(result.length >= 8);
    assert.ok(result.length <= (largura < 520 ? 18 : 32));
    for (let i = 0; i < result.length; i++) {
      const p = result[i];
      assert.ok(p.x - p.largura / 2 >= 0 && p.x + p.largura / 2 <= largura);
      assert.ok(p.y - p.altura / 2 >= 0 && p.y + p.altura / 2 <= altura);
      for (const q of result.slice(i + 1)) {
        assert.ok(Math.abs(p.x - q.x) >= (p.largura + q.largura) / 2 || Math.abs(p.y - q.y) >= (p.altura + q.altura) / 2);
      }
    }
  });
}

test("layout é determinístico e prioriza dinheiro, sem incluir saldos negativos", () => {
  const input = [...palavras, { categoria: "Ajuste", grupo: "Tipo", valor: -500 }, { categoria: "Sem valor", grupo: "Tipo", valor: NaN }];
  const a = posicionarPalavras(input, 820, 450);
  assert.deepEqual(a, posicionarPalavras([...input].reverse(), 820, 450));
  assert.equal(a[0].categoria, "Categoria eleitoral 0");
  assert.ok(a[0].tamanho >= a.at(-1).tamanho);
  assert.ok(a.every((p) => p.valor > 0 && Number.isFinite(p.valor)));
});
