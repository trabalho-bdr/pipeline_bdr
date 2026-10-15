import { render } from "preact";
import { App } from "./App";
import { ProvedorTema } from "./Tema";
import "./styles.css";
import "./temas.css";

const root = document.getElementById("app");
if (root) {
  render(<ProvedorTema><App /></ProvedorTema>, root);
}
