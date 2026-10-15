import assert from "node:assert/strict";
import test from "node:test";
import { scaleLinear } from "d3-scale";
import { CORES_UF, coresUf, corPartido } from "./coresEleitorais.ts";
import { contrasteCor, corParaFundoClaro, FUNDO_DADOS_CLARO, FUNDO_ROTULOS_CLARO, paletaAnalises } from "./paletaAnalises.ts";

test("contraste usa luminância linear e é simétrico", () => {
  assert.equal(contrasteCor("#000", "#fff"), 21);
  assert.equal(contrasteCor("#fff", "#fff"), 1);
  assert.ok(Math.abs(contrasteCor("hsl(0 100% 50%)", "#fff") - 3.99847677) < 1e-6);
  assert.equal(contrasteCor("#6689b3", FUNDO_DADOS_CLARO), contrasteCor(FUNDO_DADOS_CLARO, "#6689b3"));
});

const partidos = ["PT", "PL", "MDB", "PSDB", "UNIÃO", "PP", "PSB", "PDT", "PSD", "REPUBLICANOS", "PSOL", "NOVO", "PV", "PC DO B", "AGIR", "AVANTE", "SOLIDARIEDADE", "PODE", "CIDADANIA", "REDE", "PRD"];
test("partidos mantêm matiz e saturação, com contraste de texto no claro", () => {
  for (const partido of partidos) {
    const escura = corPartido(partido), clara = corPartido(partido, "light");
    const hsl = (cor) => cor.match(/^hsl\(([\d.]+) ([\d.]+)% ([\d.]+)%\)$/).slice(1).map(Number);
    const a = hsl(escura), b = hsl(clara);
    assert.ok(Math.abs(a[0] - b[0]) < .001, partido);
    assert.ok(Math.abs(a[1] - b[1]) < .001, partido);
    assert.ok(contrasteCor(clara, FUNDO_ROTULOS_CLARO) >= 4.5, partido);
    assert.equal(corPartido(partido, "dark"), escura);
  }
  assert.equal(corPartido("PT"), "hsl(350 52% 54%)");
  assert.equal(corPartido("PL"), "hsl(220 49% 57%)");
  assert.equal(corPartido("13", "light"), corPartido("PT", "light"));
  assert.equal(corPartido("22", "light"), corPartido("PL", "light"));
  assert.equal(new Set(partidos.map((p) => corPartido(p, "light"))).size, partidos.length);
});

test("cores de UF preservam o escuro e deixam os rótulos claros legíveis", () => {
  assert.deepEqual(coresUf("dark"), CORES_UF);
  for (const cor of Object.values(coresUf("light"))) assert.ok(contrasteCor(cor, FUNDO_ROTULOS_CLARO) >= 4.5);
});

test("escalas claras de intensidade escurecem progressivamente", () => {
  const paleta = paletaAnalises("light");
  for (const escala of [paleta.intensidade, paleta.patrimonio]) {
    const contrastes = escala.map((cor) => contrasteCor(cor, FUNDO_DADOS_CLARO));
    assert.ok(contrastes.every((c) => c >= 3));
    assert.ok(contrastes[0] < contrastes[1] && contrastes[1] < contrastes[2]);
    const interpolar = scaleLinear().domain([0, .5, 1]).range(escala);
    let anterior = 0;
    for (let i = 0; i <= 100; i++) {
      // D3 fornece rgb(); normalizamos para hexadecimal para a auditoria independente da escala.
      const rgb = interpolar(i / 100).match(/\d+/g).map(Number);
      const hex = '#' + rgb.map((n) => n.toString(16).padStart(2, '0')).join('');
      const contraste = contrasteCor(hex, FUNDO_DADOS_CLARO);
      assert.ok(contraste >= 3);
      assert.ok(contraste >= anterior - .02);
      anterior = contraste;
    }
  }
  for (const cor of [...paleta.razao, ...paleta.abstencao, ...paleta.publicidade]) assert.ok(contrasteCor(cor, FUNDO_DADOS_CLARO) >= 3, cor);
  assert.deepEqual(paletaAnalises("dark").intensidade, ["#56a6c3", "#8b79bb", "#e773ae"]);
});

test("cores já contrastantes são preservadas e fundos sem dados são distintos", () => {
  assert.equal(corParaFundoClaro("#172b4a"), "#172b4a");
  assert.ok(contrasteCor("#7d8ba3", FUNDO_DADOS_CLARO) >= 3);
  assert.ok(contrasteCor("#8f74ae", FUNDO_DADOS_CLARO) >= 3);
});
