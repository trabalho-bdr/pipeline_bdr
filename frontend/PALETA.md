# Paletas das análises

O modo escuro mantém os valores originais. O modo claro usa os mesmos papéis visuais, com escalas e cores de séries adaptadas ao fundo; não aplica inversão de imagem ou filtro de brilho ao mapa.

| Papel | Escuro | Claro |
|---|---|---|
| Tela | `#151827` | `#f3f5fb` |
| Texto principal | claro sobre azul-escuro | `#26334d` |
| Rosa dos gráficos | `#f03d94` | `#ad276e` |
| Roxo dos gráficos | `#9874eb` | `#7052a0` |
| Azul dos gráficos | `#5069d4` | `#315fa5` |
| Sem dados no mapa | `#2b2b31` | `#7d8ba3` |
| Registro sem valor | `#4a3d5c` | `#8f74ae` |
| Contexto fora da cobertura | `#19191d` | `#e3e8f1` |

## Partidos e UFs

`corPartido(sigla, tema)` e `coresUf(tema)` fornecem a mesma cor para um mesmo identificador em mapas, barras, legendas e linhas históricas. No claro, preservam matiz e saturação HSL e reduzem apenas a luminosidade até obter contraste mínimo de 4,5:1 sobre o fundo mais restritivo dos rótulos (`#ead8eb`). As cores originais não são sobrescritas e retornam ao alternar para o escuro.

Exemplos aproximados em hexadecimal, arredondados para 8 bits:

| Partido | Escuro | Claro |
|---|---|---|
| PT | `#c74d61` | `#ae374b` |
| PL | `#5c7fc7` | `#3a60ab` |
| MDB | `#6995c3` | `#3a6592` |

As cores preservam a identidade já usada pelo projeto, inclusive o vermelho do PT e o azul do PL. As demais cores continuam seguindo a atribuição do projeto; não são apresentadas como uma paleta oficial dos partidos. Siglas e legendas acompanham os dados para evitar depender apenas de diferenças de cor.

## Escalas quantitativas

`paletaAnalises(tema)` centraliza os intervalos dos mapas. As legendas usam a mesma paleta que a interpolação D3; limites, valores, percentis e filtros não mudam quando o tema muda.

| Análise no modo claro | Menor valor | Intermediário | Maior valor |
|---|---|---|---|
| Intensidade dos votos de legenda | `#6689b3` | `#806096` | `#a02366` |
| Patrimônio | `#9e7db5` | `#9d4e98` | `#9a1e5c` |
| Razão eleitos/não eleitos | `#315fa5` (0,5×) | `#877099` (1×) | `#b1266d` (2×) |

Nas escalas sequenciais claras, valores maiores ficam progressivamente mais escuros. As cores dos dados têm contraste de pelo menos 3:1 sobre `#edf1f8`; a razão mantém polos azul/rosa e centro roxo. Contornos e cores específicas distinguem seleção, ausência de dados e áreas fora da cobertura. Barras e gráficos de publicidade mantêm os matizes da versão escura, com tons mais densos no claro e separadores entre categorias.

O contraste acima é uma verificação das paletas nos fundos declarados, não uma certificação de acessibilidade de toda a aplicação. Rótulos, valores e estados também permanecem disponíveis em texto.

## Verificação

```powershell
cd frontend
npm.cmd run test:cores
npm.cmd run build
```

Os testes verificam luminância, contraste, conservação de matiz e saturação, aliases dos partidos, recuperação da paleta escura e progressão das escalas, incluindo valores interpolados.
