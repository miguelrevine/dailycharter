# PROGRESO — DailyCharter

Última actualización: 2026-07-15 ~21:20 (sesión autónoma, retomada tras cierre de la anterior)

## Estado general

| Fase | Estado |
|---|---|
| 0. Mover proyecto a `C:\Users\migue\Proyectos\dailycharter` | ✅ Hecho |
| 1. Comprobar entorno | ✅ Hecho (git, node, npm, gh, wrangler instalados; Ollama OK con qwen3:14b) |
| 2. Repos y despliegue web | 🔶 PARCIAL — git init + commits ✅; deploy a GitHub Pages ⛔ bloqueado: `gh auth status` verificado hoy → **no autenticado** |
| 3. Piloto de contenido (plan 90) | 🔄 EN CURSO — generación reanudada desde checkpoint tras arreglar 2 bugs (ver historial abajo). Monitor activo avisa cada 15 píldoras |
| 4. Control de calidad | ⏳ Pendiente de que termine fase 3 |
| 5. Generación completa (180/270/365) | ⏳ Pendiente del visto bueno del usuario en fase 4 |
| 6. Motor de emails (Cloudflare) | 🔶 PREP ✅ ampliada — smoke test LOCAL pasado hoy (ver abajo). Deploy real bloqueado: `wrangler whoami` verificado hoy → **no autenticado**; falta también API key de Resend |
| 7. Cablear web ↔ motor | ⏳ Pendiente de fase 6 |
| 8. Prueba de fuego | ⏳ Pendiente de fases 6-7 |

## Historial de la generación (fase 3) — IMPORTANTE para retomar

La sesión anterior decía "generación en curso"; **no era cierto al retomar**: el proceso había
muerto. Dos crashes distintos, ambos arreglados y commiteados hoy:

1. **UnicodeEncodeError** (píldora 3/90): `open()` sin `encoding` usa cp1252 en Windows y no puede
   escribir caracteres de fórmulas ('₀'). Fix: `encoding="utf-8"` en los 3 file handles de
   `pill_factory.py`. Commit `124a544`.
2. **AttributeError** (píldora 4/90): el modelo a veces devuelve `question.choices` como strings en
   vez de objetos; `c.get("key")` reventaba fuera del bucle de reintentos. Fix: esos errores de forma
   ahora cuentan como intento fallido y se reintenta (retries 2→4). Commit `81e7e42`.

Estado actual: generación corriendo en background (`python -u ... generate --plan 90 --model qwen3:14b`),
log en `pill-factory/generate-90.log`, checkpoint en `pill-factory/plans/plan-90.json.partial`
(se escribe en cada píldora). **Si esta sesión muere: relanzar el mismo comando; reanuda solo.**

## Fase 6 — smoke test local pasado (2026-07-15)

Sin credenciales de Cloudflare se puede probar todo en local, y funciona:
- `npx wrangler d1 execute dailycharter --local --file=schema.sql` → OK, sin errores.
- `.dev.vars` creado con secrets dummy (gitignorado, NO es un secret real).
- `npx wrangler dev --port 8787 --test-scheduled` → `/health` responde `{"ok":true}` (HTTP 200),
  y el cron disparado a mano (`/__scheduled?cron=0+*+*+*+*`) corre limpio: `cron h19: sent=0 skipped=0 failed=0`.
El deploy real de fase 6 queda reducido a: login + crear D1 + poner database_id + secrets reales +
rellenar SITE_URL/FROM_EMAIL + deploy.

## Fase 1 — entorno (verificado hoy)

Python 3.14.5, pip, pypdf, requests ✅ · git ✅ (repo con 4 commits) · node/npm ✅ ·
wrangler 4.110.0 local en mail-engine/ ✅ · gh instalado pero **sin login** ·
Ollama en localhost:11434 ✅ con `qwen3:14b` (único modelo).

## PDFs

Los 5 PDFs están en `pill-factory/pdfs/` renombrados por contenido real
(01-ethics-quant … 05-derivatives-portfolio); `scan` los mapea correctamente a los 7 topics.
Detalle del renombrado en el historial git de este archivo si hiciera falta.

## Qué necesito de ti (sin esto no puedo cerrar las fases 2 y 6)

- **`gh auth login`** — corre `! gh auth login` para desbloquear el deploy de la web (fase 2).
- **`wrangler login`** (Cloudflare) — para la fase 6.
- **API key de Resend** — para la fase 6 (antes: cuenta en resend.com + dominio verificado SPF/DKIM).
- **Checkpoint de calidad fase 4**: cuando la generación termine y valide, te dejaré `review.html`
  listo y esperaré tu OK antes de lanzar la fase 5.
