# PROGRESO — DailyCharter

Última actualización: 2026-07-15 ~22:50 (sesión autónoma)

## Estado general

| Fase | Estado |
|---|---|
| 0. Mover proyecto a `C:\Users\migue\Proyectos\dailycharter` | ✅ Hecho |
| 1. Comprobar entorno | ✅ Hecho (git, node, npm, gh, wrangler instalados; Ollama OK con qwen3:14b) |
| 2. Repos y despliegue web | ✅ HECHO — repo público `miguelrevine/dailycharter` (master + gh-pages via subtree); web viva en https://miguelrevine.github.io/dailycharter/ (curl 200 verificado) |
| 3. Piloto de contenido (plan 90) | ✅ HECHO — `plan-90.json` (L1-90 v20260715, 90 píldoras, qwen3:14b), commit `12623c6` |
| 4. Control de calidad | ✅ HECHO — validación limpia + **visto bueno del usuario recibido** |
| 5. Generación completa (180/270/365) | 🔄 EN CURSO — 180 ✅ generado, validación marcó **23 píldoras** (pendientes de `regen` cuando acabe la cadena, días en `pill-factory/validate-180.log`); 270 generándose desde las 12:01. Si muere: relanzar `bash pill-factory/overnight.sh > pill-factory/overnight.log 2>&1 &` (reanuda de checkpoint) |
| 6. Motor de emails (Cloudflare) | ✅ HECHO (salvo seed) — D1 `dailycharter` (id `d520a18f-a3d6-4884-b76d-377d9d4d2fd1`, WEUR, 6 tablas), worker en https://dailycharter-engine.miguelrevine.workers.dev (`/health` OK), cron horario, secrets TOKEN_SECRET y ESP_API_KEY configurados (la key de Resend SOLO existe como secret, nunca en archivos), SITE_URL=https://www.daily-charter.com y FROM_EMAIL=pills@daily-charter.com desplegados. Seed de planes: cuando acabe la generación |
| 6b. Dominio daily-charter.com | 🔶 EN CURSO — emails placeholder sustituidos (hello@/pills@/privacy@daily-charter.com), site/CNAME creado, custom domain configurado en Pages (status: building), CORS verificado para el nuevo origin. ⛔ ESPERANDO: DNS en Cloudflare (la crea el usuario; registros listados en el parte) → luego Enforce HTTPS cuando emita el certificado |
| 7. Cablear web ↔ motor | ✅ HECHO — WORKER_URL en index.html, quiz.html reescrito contra la API real (DEMO fuera), web redesplegada. De paso: **bug de CORS del worker arreglado** (ACAO enviaba URL con path; ahora envía el origin — verificado con curl) |
| 8. Prueba de fuego | ⏳ Pendiente de fases 6-7 |

## Fase 4 — QA cerrado por mi parte, pendiente del humano

- `validate_plan.py --pdf-dir --review 10` → **"Plan 'L1-90' v20260715 is publishable (90 pills, 0 warning(s))"**.
- El chequeo de originalidad marcó 13 píldoras al inicio; hicieron falta 6 rondas de regen. Los casos
  duros (días 5 y 83) solo cedieron prohibiendo en el prompt las frases exactas marcadas (`regen --avoid`)
  y forzando enunciado tipo escenario. Ese es el patrón a seguir en fase 5 si algo se resiste.
- **`review.html` está en la raíz del proyecto** con las 10 píldoras de muestra. ⛔ Parada obligatoria:
  leerlas y dar el visto bueno (o pedir cambios de modelo/temperatura/prompt) antes de la fase 5.

## Historial de la generación (fase 3) — IMPORTANTE para retomar

La sesión anterior decía "generación en curso"; **no era cierto al retomar**: el proceso había
muerto. Dos crashes distintos, ambos arreglados y commiteados:

1. **UnicodeEncodeError** (píldora 3/90): `open()` sin `encoding` usa cp1252 en Windows y no puede
   escribir caracteres de fórmulas ('₀'). Fix: `encoding="utf-8"` en los 3 file handles de
   `pill_factory.py`. Commit `124a544`.
2. **AttributeError** (píldora 4/90): el modelo a veces devuelve `question.choices` como strings en
   vez de objetos; `c.get("key")` reventaba fuera del bucle de reintentos. Fix: esos errores de forma
   ahora cuentan como intento fallido y se reintenta (retries 2→4). Commit `81e7e42`.

Después hubo dos fallos más, también arreglados y commiteados: reintento con backoff ante errores
HTTP de Ollama + checkpoint por píldora en `regen`, y **fail-fast si el modelo pedido no está en
Ollama** (dos runs de regen se perdieron porque `regen` sin `--model` usa el default `llama3.1`,
que no está descargado — pasar SIEMPRE `--model qwen3:14b`).

La generación terminó limpia: 90/90 píldoras. Para fase 5 (180/270/365): mismo comando `generate`
con `--plan 180|270|365 --model qwen3:14b`; tiene checkpoints y reanuda solo si se corta.

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

## Extras de esta sesión

- `review.html` ahora es interactivo (plantilla `pill-factory/review_template.html`): quiz clicable
  con explicaciones, veredicto 👍/👎 + notas por píldora, progreso, export de feedback en markdown.
  Verificado en Chrome. Se sirve en http://localhost:8901/review.html mientras esta sesión viva.
- Subdominio workers.dev registrado: `miguelrevine.workers.dev` (vía API, wrangler v4 ya no tiene
  el comando `subdomain`).

## Qué necesito de ti

1. **API key de Resend** (única credencial pendiente) — antes: cuenta en resend.com + dominio
   verificado con SPF/DKIM. Con ella: `wrangler secret put ESP_API_KEY`, FROM_EMAIL real en
   wrangler.toml, redeploy y verificación. Dime también qué remitente quieres (p.ej.
   `DailyCharter <pills@tudominio.com>`).
2. Nada más: fases 2 y 4 cerradas, 5 corriendo, 6 casi cerrada, 7 la haré mientras espero.
