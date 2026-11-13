// Nodo Code "Verificar cifras" (n8n, JavaScript). Misma lógica que motor/verificar.py.
// Entrada: $json.redaccion (salida de Sonnet) y $json.afirmaciones (del plan). Salida: problemas[].
const CAUSALES = ["provoca","provocó","causa","causó","debido a","por culpa de","gracias a","hace que","dispara","se debe a","como consecuencia","consecuencia de","explica que"];
const SENSAC = ["brutal","escándalo","alarmante","dramático","increíble","bomba","se dispara","se desploma","hundimiento","catástrofe","por fin","vergüenza","lamentable","afortunadamente","por desgracia"];
const RE = /(?<![\w.,])[−-]?\d{1,3}(?:\.\d{3})*(?:,\d+)?(?![\w])|(?<![\w.,])[−-]?\d+(?:,\d+)?(?![\w])/g;
const cifras = t => (String(t).match(RE) || []).map(s => parseFloat(s.replace("−","-").replace(/\./g,"").replace(",", ".")));

return $input.all().map(item => {
  const r = item.json.redaccion, afs = item.json.afirmaciones, esCruce = item.json.detector === "cruce_variables";
  const permitidos = [];
  for (const a of afs) {
    permitidos.push(+a.valor, ...cifras(a.texto_valor), ...cifras(a.periodo || ""));
    for (const o of (a.origenes || [])) permitidos.push(...cifras(o.dataset || ""));
  }
  const textos = [r.titulo_publicacion, r.portada.titulo, r.portada.subtitulo, r.pie_de_foto, r.que_se_mide, r.alt,
                  ...r.resumen, ...r.diapositivas.flatMap(d => [d.titulo, d.nota || ""])].map(t => String(t).replace(/<[^>]+>/g, ""));
  const problemas = [];
  for (const t of textos) {
    for (const c of cifras(t)) {
      if (c >= 1900 && c <= 2100 && Number.isInteger(c) && afs.some(a => (a.periodo || "").includes(String(c)))) continue;
      if ([1,2,3,4,5,10].includes(c) && new RegExp(`\\b(las|los|top)\\s+${c}\\b`, "i").test(t)) continue;
      if (!permitidos.some(p => Math.abs(c - p) <= Math.max(0.005 * Math.abs(p), 0.051))) problemas.push(`Cifra sin respaldo: ${c} en «${t.slice(0,80)}»`);
    }
    const n = t.toLowerCase();
    for (const w of SENSAC) if (n.includes(w)) problemas.push(`Término no neutral «${w}»`);
    if (esCruce) for (const w of CAUSALES) if (n.includes(w)) problemas.push(`Lenguaje causal «${w}» en un cruce`);
  }
  // Longitudes (el código cuenta, no el modelo)
  const palabras = s => String(s).trim().split(/\s+/).length;
  if (palabras(r.portada.titulo) > 12) problemas.push("Titular de portada de más de 12 palabras");
  r.resumen.forEach((p, i) => palabras(p) > 20 && problemas.push(`Punto ${i+1} del resumen de más de 20 palabras`));
  if (/https?:\/\//.test(r.pie_de_foto)) problemas.push("URL en el pie de foto");
  return {json: {...item.json, problemas, ok: problemas.length === 0}};
});
