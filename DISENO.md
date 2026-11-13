# Cifras para todos: diseño de la automatización

*Diseño inicial del 13 de noviembre de 2026. Reutiliza servicios, credenciales y métodos del BOE y del Congreso (ver `cuentas-y-decisiones.md`).*

## Decisiones
- **Cuenta:** CIFRAS para todos, **@cifrasparatodos** (Jordi; las variantes con "el/los" estaban cogidas). Misma identidad visual que el resto de la serie.
- **Decisiones de enfoque (opción recomendada, confirmada por Jordi el 13 de noviembre de 2026):**
  1. **Por fases.** Fase 1: INE, REData y BCE (sin claves). Fase 2: AEMET (API key gratuita) y e·sios (token personal de REE). Fase 3: cruces con AEMET y descubrimiento de datasets en datos.gob.es.
  2. **Motor en Python dentro de GitHub Actions** (gratis en un repositorio público). n8n coordina, Claude redacta, Telegram aprueba e Instagram publica, como en el BOE.
  3. **Ritmo (decisión de Jordi, 13 de noviembre de 2026):** como máximo **10 carruseles de novedades al día**. Si ninguna supera el umbral, se propone **1 pieza de reserva** (atemporal: comparación de hace 20 años, récords de la serie, cruces). Aprobación con botones de Telegram, de lunes a sábado. Coste estimado de IA con 10 carruseles: unos 10 céntimos por carrusel, es decir, hasta 1 € al día. La API de Instagram permite hasta 100 publicaciones cada 24 horas.

## Fuentes (comprobadas el 13 de noviembre de 2026)
| Fuente | Acceso | Notas |
|---|---|---|
| INE (Tempus3) | `servicios.ine.es/wstempus/js/ES/DATOS_TABLA/{id}?nult=N`, `DATOS_SERIE/{cod}`, `TABLAS_OPERACION/{op}` | Sin clave. ✅ Probado con la tabla 65349 (EPA por provincias, 3T 2026). **El IPC pasó a base 2025 en enero de 2026:** la serie IPC251852 termina en diciembre de 2025. Por eso el motor busca las tablas por operación y nombre, y avisa de las series que dejan de actualizarse. |
| REE · REData | `apidatos.ree.es/es/datos/{categoria}/{widget}?start_date&end_date&time_trunc` | Sin clave (documentación oficial). No accesible desde el entorno de Claude; sí desde GitHub Actions. Pedir por tramos de un año. |
| BCE · ECB Data Portal | `data-api.ecb.europa.eu/service/data/{flujo}/{clave}?format=csvdata&startPeriod&lastNObservations&updatedAfter` | Sin clave. Mismo caso: se prueba en la primera ejecución de la Action. |
| AEMET OpenData (fase 2) | `opendata.aemet.es/opendata/api/...` en dos pasos (la respuesta trae la URL de los datos) | API key gratuita con un correo. Guardarla como secreto `AEMET_API_KEY` del repositorio. |
| e·sios (fase 2) | `api.esios.ree.es` | Token personal que se pide a REE. |
| datos.gob.es (fase 3) | API del catálogo | Para descubrir datasets, no para publicar directamente. |

## Trazabilidad (regla de oro)
- **Ninguna cifra la escribe la IA por su cuenta.** El motor convierte cada cifra en una *afirmación* con: fuente, dataset/tabla, indicador, URL exacta de la consulta, periodo, valor original y tipo.
- **Tipos:** DATO OFICIAL (publicado tal cual), CÁLCULO DERIVADO (operación propia: variaciones, recuentos, redondeos), COMPARACIÓN (diferencias o cocientes entre datos oficiales) y ESTIMACIÓN (aproximaciones). Todo lo que no es DATO OFICIAL lleva su fórmula.
- Cada diapositiva muestra en el pie el tipo de sus cifras; la última explica los tipos.
- **Verificador automático** (`motor/verificar.py` y `n8n/verificar.js`): toda cifra de los textos debe coincidir con una afirmación del carrusel. También rechaza vocabulario sensacionalista y, en los cruces, lenguaje causal. Probado: rechaza "casi un 19 %" cuando el dato es 18,87 %.
- Los valores de los gráficos los pone siempre el código.

## Insight Engine (`motor/detectores.py`)
Detectores deterministas, sin IA:
- **Series temporales:** máximo/mínimo histórico y de 5, 10 y 20 años ("el más alto desde…"); cambio respecto al periodo anterior y cambio interanual, comparados con la volatilidad de la propia serie (z ≥ 2); tendencias sostenidas (6 meses, 4 trimestres o 10 días seguidos); cambios de tendencia; hitos redondos ("supera por primera vez los 50 millones"); hoy frente a la media histórica de esas fechas; comparación con hace 20 años.
- **Cortes territoriales:** mapa, top/bottom, ratio entre el máximo y el mínimo, outliers (z robusto con mediana y MAD) y brechas entre grupos (mujeres frente a hombres…).
- **Cruces:** Spearman sobre las **variaciones** (no sobre los niveles, para no confundir dos tendencias de fondo), con n ≥ 24, |ρ| ≥ 0,6 y p < 0,01. Siempre con redacción no causal.
- **Puntuación** = peso del detector × intensidad × interés del indicador (1–3) × frescura × novedad (penaliza repetir indicador o formato en 10 días y nunca repite un insight). Umbral de noticia: 0,45.
- **Agrupación:** un carrusel = un insight principal + hasta 2 secundarios de la misma fuente con otros formatos (p. ej. MAPA + TOP / BOTTOM + brecha por sexo).
- **Formatos y visual:** RÉCORD → líneas con punto destacado; DATO → contador o barras; MAPA → mapa de cuadrícula; TOP / BOTTOM → barras con línea de la media; COMPARACIÓN TEMPORAL → antes/ahora; HOY VS MEDIA HISTÓRICA → barra con banda habitual; CURIOSIDAD → pictograma de 100 personas o comparación de grupos; ¿SABÍAS QUE…? → outlier destacado.
- **Avisos que no paran el día:** fuente caída, serie congelada y revisiones de datos ya publicados.

## Diseño visual (`render/plantilla.html`)
- Identidad de la serie: Plus Jakarta Sans 800 + Atkinson Hyperlegible, paleta petróleo/crema/tinta/melocotón/niebla, logo con el bocadillo y "CIFRAS / para todos". JPEG de 1080 × 1350 con Playwright.
- **Mapa de cuadrícula (cartograma):** un cuadrado por provincia, con Canarias en un recuadro aparte. Escala de 5 tonos de azul petróleo con tramos redondos. Se lee en 3 segundos y no necesita archivos de geometría. Si se quiere un coroplético con fronteras reales, se puede añadir un GeoJSON al repositorio.
- Etiqueta del formato con emoji en la portada (🗺️ MAPA, 🚨 RÉCORD…). Melocotón solo para el dato destacado.
- Estructura: 1 portada · 2 dato principal · 3–5 contexto · 6 en resumen · 7 fuente y método.
- **Muestra hecha** con datos reales: paro por provincias de la EPA del 3T 2026 (7 diapositivas: portada, 10,18 % con pictograma, mapa, top/bottom, mujeres frente a hombres, resumen y fuente).

## Repositorio `cifras-para-todos` (GitHub, público)
```
config/indicadores.json   catálogo (fase 1: 12 INE, 3 REData, 6 BCE, 3 cruces)
config/provincias.json    nombres INE → abreviatura, CCAA y posición en el mapa
motor/                    fuentes, series y almacén, detectores, motor, verificar, carrusel, ejecutar
render/                   plantilla.html, render.py, hoja.py, fuentes_tipo/
n8n/                      prompt_redaccion.md, verificar.js
datos/historico/          un CSV por serie (el histórico vive en el repositorio)
datos/plan/<fecha>.json   insights del día
datos/lotes/<lote>.json   carruseles con textos verificados (dispara el render)
datos/publicados.json     lo ya publicado (para la novedad)
.github/workflows/        analizar.yml (workflow_dispatch) y render.yml (push en datos/lotes)
```

## Flujo n8n "Cifras" (por montar)
**Rama diaria**
1. Schedule Trigger, lunes a sábado (hora por decidir; el INE publica a las 9:00).
2. HTTP: `POST /repos/institucionesparatodos/cifras-para-todos/actions/workflows/analizar.yml/dispatches` con `resume_url`.
3. Wait (On Webhook Call, máximo 20 minutos) → recibe el plan.
4. If "Sin carruseles" → aviso por Telegram con los avisos del día y los descartados.
5. Por carrusel: Sonnet redacta (`n8n/prompt_redaccion.md`) → Code "Verificar cifras" (`n8n/verificar.js`) → si falla, Haiku corrige una vez con la lista de problemas → si sigue fallando, se descarta y se avisa.
6. Code "Montar lote": une cifras y gráficos (del plan) con los textos (de Sonnet) → PUT `datos/lotes/<lote>.json` → Wait → la Action `render` genera los JPEG y la hoja de vista previa y llama a la resume URL.
7. Telegram: hoja de vista previa + pie + avisos, con botones **📤 Publicar** (`n|p|<lote>|<n>`) y **🗑️ Descartar** (`n|d|<lote>|<n>`).

**Publicación:** "Telegram – Decisiones" reparte el prefijo `n` a la rama de publicación del flujo "Cifras", copiada de la del BOE (contenedores → carrusel → `media_publish`). Al publicar, el insight se añade a `datos/publicados.json`.

## Pendiente
1. Crear @cifrasparatodos en Instagram con la configuración del BOE (Empresa, *Sitio web educativo*, 2FA) y su página de Facebook para la API. Propuesta de bio: "Las estadísticas de España, explicadas para todos 📊 · Datos oficiales (INE, REE, BCE, AEMET), sin opiniones. Divulgación independiente, no oficial."
2. Crear el repositorio público `cifras-para-todos`, subir el código y activar GitHub Pages. Token *fine-grained* con permisos de Contents y **Actions** (lectura y escritura) para lanzar `analizar`.
3. Primera ejecución manual de `analizar`: validar los ids del catálogo marcados como no verificados (REData, BCE y tablas del INE) y cargar el histórico.
4. Pedir la API key de AEMET (fase 2).
5. Montar el flujo de n8n y añadir el prefijo `n` a "Telegram – Decisiones".
6. Jordi revisa la muestra (diseño del mapa, pictograma y pie con los tipos de cifra).
