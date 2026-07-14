# PROGRESO — DailyCharter

Última actualización: sesión autónoma en curso (fecha del sistema: 2026-07-15)

## Estado general

| Fase | Estado |
|---|---|
| 0. Mover proyecto a `C:\Users\migue\Proyectos\dailycharter` | ✅ Hecho |
| 1. Comprobar entorno | ✅ Hecho (ver tabla abajo) |
| 2. Repos y despliegue web | ⛔ BLOQUEADA — falta `git` |
| 3. Piloto de contenido (plan 90) | 🔄 En curso |
| 4. Control de calidad | ⏳ Pendiente de fase 3 |
| 5. Generación completa (180/270/365) | ⏳ Pendiente de aprobación fase 4 |
| 6. Motor de emails (Cloudflare) | ⛔ BLOQUEADA — falta `wrangler`, falta login Cloudflare, falta API key Resend |
| 7. Cablear web ↔ motor | ⏳ Pendiente de fase 6 |
| 8. Prueba de fuego | ⏳ Pendiente de fases 6-7 |

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

Los 5 PDFs (`CFA_Public_1..5.pdf`) YA estaban en `pill-factory/pdfs/` al mover el proyecto. No ha hecho falta pedir confirmación de copia (regla 6).

## Bloqueado — y por qué

1. **Fase 2 (git init, deploy GitHub Pages)**: imposible sin `git`. Sin `gh` también costaría más
   (tendría que usar la API REST de GitHub con un token, menos robusto que `gh`).
2. **Fase 6 (Cloudflare Worker + D1)**: imposible sin `wrangler` (requiere `npm`, que requiere `node`).
   Además necesito: (a) que hagas login de `wrangler` (Cloudflare) tú mismo, (b) la API key de Resend.

## Qué necesito de ti

- **Decisión de instalación de sistema**: ¿instalo git, Node.js LTS, gh y wrangler con winget (comandos
  arriba), o prefieres instalarlos tú? Sin esto no puedo avanzar en fases 2, 6, 7, 8.
- **Login de GitHub (`gh auth login`)** — cuando gh esté instalado.
- **Login de Cloudflare (`wrangler login`)** — cuando wrangler esté instalado.
- **API key de Resend** — para la fase 6, cuando lleguemos ahí.
- **Checkpoint de calidad fase 4**: en cuanto `review.html` esté listo, te aviso aquí y espero tu OK
  antes de lanzar la fase 5 (generación completa 180/270/365).

## Avance en paralelo mientras espero

Mientras se resuelve el bloqueo de fase 2, sigo con la fase 3 (scan + generación del plan de 90 días
con Ollama/qwen3:14b), que no depende de git ni de ninguna credencial externa.
