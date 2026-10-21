import { useState } from "preact/hooks";
import "./foto-candidato.css";

export type Foto = { foto_url?: string | null; foto_ano?: number | null; foto_status?: string;
  foto_anterior?: boolean; foto_cobertura_completa?: boolean };
type Props = Foto & { id_candidato: string; nome: string; tamanho?: number };

function Retrato({ nome, foto_url, tamanho = 48 }: Props) {
  const [erro, setErro] = useState(false);
  const iniciais = nome.trim().split(/\s+/).slice(0, 2).map((p) => p[0]).join("") || "?";
  return <span class="foto-candidato-retrato" style={{ width: tamanho, height: tamanho }}>
    {foto_url && !erro ? <img src={foto_url} width={tamanho} height={tamanho} loading="lazy" decoding="async"
      alt={`Foto oficial de ${nome}`} onError={() => setErro(true)} />
      : <span role="img" aria-label={`Retrato indisponível de ${nome}`}>{iniciais}</span>}
  </span>;
}

export function FotoCandidato(props: Props) {
  // Remonta o estado de erro e o elemento img quando muda a pessoa OU a imagem.
  const identidade = `${props.id_candidato}:${props.foto_url || ""}:${props.foto_ano || ""}`;
  return <span class="foto-candidato">
    <Retrato key={identidade} {...props} />
    {props.foto_url && props.foto_ano && <small class="foto-candidato-ano"
      title={props.foto_anterior ? "Foto anterior à última candidatura identificada" : "Foto principal da pessoa; os dados da análise pertencem à eleição selecionada"}>
      Foto: candidatura de {props.foto_ano}{props.foto_anterior ? " (anterior)" : ""}
    </small>}
  </span>;
}
