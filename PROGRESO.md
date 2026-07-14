# PROGRESO — DailyCharter

Última actualización: sesión autónoma en curso (fecha del sistema: 2026-07-15)

## Estado general

| Fase | Estado |
|---|---|
| 0. Mover proyecto a `C:\Users\migue\Proyectos\dailycharter` | ✅ Hecho |
| 1. Comprobar entorno | ✅ Hecho (git, node, npm, gh, wrangler instalados con tu aprobación) |
| 2. Repos y despliegue web | 🔶 PARCIAL — git init + primer commit hechos; deploy a GitHub Pages ⛔ bloqueado: falta `gh auth login` (tuyo) |
| 3. Piloto de contenido (plan 90) | 🔄 En curso — generación de 90 píldoras con Ollama/qwen3:14b corriendo en background (~80-110 min ETA) |
| 4. Control de calidad | ⏳ Pendiente de que termine fase 3 |
| 5. Generación completa (180/270/365) | ⏳ Pendiente de tu aprobación en el checkpoint de fase 4 |
| 6. Motor de emails (Cloudflare) | 🔶 PREP — wrangler 4.110.0 instalado localmente en mail-engine/ y funcional. Bloqueado: falta `wrangler login` (tuyo) y API key de Resend (tuya) |
| 7. Cablear web ↔ motor | ⏳ Pendiente de fase 6 |
| 8. Prueba de fuego | ⏳ Pendiente de fases 6-7, y de tu confirmación de email recibido |

## Fase 1 — Tabla de entorno

| Herramienta | Estado | Comando de instalación |
|---|---|---|
| Python | ✅ 3.14.5 | — |
| pip | ✅ 26.1.2 | — |
| pypdf (pip) | ✅ instalado ahora (6.14.2) | — |
| requests (pip) | ✅ 2.34.2 ya presente | — |
| git | ❌ NO instalado | `winget install --id Git.Git -e --source winget` |
| node | ❌ NO instalado | `winget install --id OpenJS.NodeJS.LTS -e --source winget` |
| npm | ❌ NO instalado (viene con node) | (incluido con Node.js) |
| wrangler | ❌ NO instalado (requiere npm) | `npm install -g wrangler` (tras instalar Node) |
| gh (GitHub CLI) | ❌ NO instalado | `winget install --id GitHub.cli -e --source winget` |
| Ollama server | ✅ corriendo en localhost:11434 | — |
| Modelo Ollama | ✅ `qwen3:14b` descargado (único modelo disponible; será el usado en fase 3) | — |

**No he instalado git/node/npm/gh/wrangler** porque tu propia instrucción de fase 1 dice explícitamente
"no instales nada de sistema sin preguntarme". Pregunta lanzada al usuario — ver sección "Necesito de ti".

## PDFs

Los 5 PDFs YA estaban en `pill-factory/pdfs/` al mover el proyecto (regla 6: no hizo falta pedir
confirmación de copia). Se llamaban genéricamente `CFA_Public_1..5.pdf`, lo que hacía que
`pill_factory.py scan` los mapeara todos a topic "General" (no existe en `TOPIC_WEIGHTS`, así que la
generación real habría quedado sin texto de referencia). Los inspeccioné (extraje el índice de cada
uno) e identifiqué su contenido real:

| Archivo original | Contenido real (por índice) | Renombrado a |
|---|---|---|
| CFA_Public_1.pdf | Ethics and Trust, Code/Standards, GIPS, Time Value of Money | `01-ethics-quant.pdf` |
| CFA_Public_2.pdf | Demand/Supply, Market Structures, Aggregate Output | `02-economics.pdf` |
| CFA_Public_3.pdf | FSA intro, Financial Reporting Standards, Income Statements | `03-reporting-analysis.pdf` |
| CFA_Public_4.pdf | Corporate Governance/ESG, Capital Budgeting, Cost of Capital | `04-corporate-finance.pdf` |
| CFA_Public_5.pdf | Derivative Markets/Pricing, Alt Investments, Portfolio Mgmt | `05-derivatives-portfolio.pdf` |

Tras el renombrado, `scan` mapea correctamente los 7 topics del temario CFA L1. Verificado con
`pill_factory.py scan --pdf-dir pill-factory/pdfs` (salida en el log de la sesión).

## Bloqueado — y por qué

1. **Fase 2, deploy a GitHub Pages**: `git` ya instalado y usado (init + primer commit ✅). Falta
   `gh auth login` — solo tú tienes esa credencial. En cuanto esté, ejecuto
   `gh repo create dailycharter --public --source=site --remote=origin --push` (o equivalente) y
   habilito Pages, luego verifico con `curl -I` que responde 200.
2. **Fase 6 (Cloudflare Worker + D1)**: `wrangler` 4.110.0 ya instalado y funcional (local, en
   `mail-engine/`, vía `npx wrangler`). Falta: (a) `wrangler login` (Cloudflare, tuyo),
   (b) API key de Resend (tuya). `TOKEN_SECRET` lo genero yo (string aleatorio largo) cuando lleguemos.

## Qué necesito de ti

- **`gh auth login`** — corre `! gh auth login` cuando puedas, para desbloquear el deploy de la web (fase 2).
- **`wrangler login`** (Cloudflare) — para la fase 6, cuando lleguemos ahí.
- **API key de Resend** — para la fase 6 (antes crea cuenta en resend.com y verifica dominio con SPF/DKIM).
- **Checkpoint de calidad fase 4**: en cuanto `review.html` esté listo, te aviso aquí y espero tu OK
  antes de lanzar la fase 5 (generación completa 180/270/365).

## Avance en paralelo mientras espero

- Fase 3: generación del plan de 90 días corriendo en background (Ollama/qwen3:14b), log en
  `pill-factory/generate-90.log`, checkpoint automático en `pill-factory/plans/plan-90.json.partial`.
- Fase 6 prep: `wrangler` instalado y verificado localmente en `mail-engine/` (con `package.json` propio,
  scripts de instalación de `esbuild`/`workerd`/`sharp` aprobados explícitamente — npm 11+ los bloquea
  por defecto).
