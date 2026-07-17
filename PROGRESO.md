# PROGRESO — DailyCharter

Última actualización: 2026-07-18 ~00:00 (sesión autónoma — fase 8 retomada, envío real confirmado)

## Estado general

| Fase | Estado |
|---|---|
| 0. Mover proyecto a `C:\Users\migue\Proyectos\dailycharter` | ✅ Hecho |
| 1. Comprobar entorno | ✅ Hecho (git, node, npm, gh, wrangler instalados; Ollama OK con qwen3:14b) |
| 2. Repos y despliegue web | ✅ HECHO — repo público `miguelrevine/dailycharter`; web viva en https://www.daily-charter.com (dominio propio, ver 6b) |
| 3. Piloto de contenido (plan 90) | ✅ HECHO — `plan-90.json` (L1-90 v20260715, 90 píldoras, qwen3:14b) |
| 4. Control de calidad | ✅ HECHO — validación limpia + visto bueno del usuario |
| 5. Generación completa (180/270/365) | ✅ **HECHO — los 4 planes (90/180/270/365) generados, validados a 0 errores/0 avisos y SEMBRADOS en D1.** Verificado: 4 filas en `plans`, **905 píldoras totales** (90+180+270+365) |
| 6. Motor de emails (Cloudflare) | ✅ HECHO — D1 `dailycharter` (id `d520a18f-a3d6-4884-b76d-377d9d4d2fd1`), worker en https://dailycharter-engine.miguelrevine.workers.dev, cron horario, secrets TOKEN_SECRET/ESP_API_KEY/ADMIN_TOKEN configurados (nunca en archivos), SITE_URL/FROM_EMAIL en daily-charter.com |
| 6b. Dominio daily-charter.com | ✅ HECHO — HTTPS enforced, apex→www 301, Resend Verified |
| 7. Cablear web ↔ motor | ✅ HECHO — WORKER_URL/API_BASE reales, bug de CORS corregido |
| 8. Prueba de fuego (email real a miguelrevine@gmail.com) | 🔶 **EN CURSO — píldora 001 enviada y confirmada por Resend** (esp_id `a81d2ecc-ad53-4f34-bd73-2a3bbba1c43e`). Esperando que el usuario confirme recepción/SPF-DKIM/clic en quiz/unsubscribe para cerrar del todo — ver sección dedicada abajo |
| 9. Cuentas de usuario (accounts-design.md) | ✅ HECHO — ver sección dedicada abajo |

## Fase 8 — prueba de fuego (2026-07-18) — retomada desde cero

1. **Alta real desde el formulario**: se borró la fila antigua sin usar (nunca había tenido envíos)
   y se dio de alta `miguelrevine@gmail.com` de verdad, clicando el formulario de
   https://www.daily-charter.com en el navegador (plan 90, botón "Send my first pill" →
   "Check your inbox ✓"). Verificado en D1: `plan_id='L1-90'`, `plan_version='v20260715'`,
   `next_day=1`, `status='active'`.
2. **Envío de la píldora 001**: `send_hour_utc` ajustado a la hora UTC del momento (23) y disparo
   del cron. **Problema encontrado**: `wrangler dev --test-scheduled` (incluso con `--remote`) usa
   los secrets de `.dev.vars` local, no los reales — y los secrets de producción son de solo
   escritura (`wrangler secret put` no permite leerlos de vuelta), así que esa vía daba 401 de
   Resend con la key dummy. Solución: añadí `POST /api/admin/run-cron` (protegido con
   `ADMIN_TOKEN`, mismo patrón que `/api/admin/subscribers`) que llama a la MISMA función que usa
   el cron real, contra el worker desplegado de verdad (secrets y D1 reales). Queda como utilidad
   permanente para reenviar manualmente sin esperar a la hora en punto.
   **Confirmado por la respuesta de la API de Resend**: `{"sent":1,"skipped":0,"failed":0,
   "details":[{"email":"miguelrevine@gmail.com","day":1,"esp":{"id":
   "a81d2ecc-ad53-4f34-bd73-2a3bbba1c43e"}}]}`. D1 confirma `next_day=2` y fila en `sends`
   (day=1, sent_at 2026-07-17 23:56:47). `send_hour_utc` restaurado a 6 después.
3. **Avisado al usuario** ("Mira tu bandeja") con la checklist de qué comprobar.
4. ⏳ **Pendiente de tu confirmación** para ejecutar y pegar aquí:
   ```sql
   -- tras el clic en el botón B del quiz:
   SELECT * FROM attempts WHERE subscriber_id=(SELECT id FROM subscribers WHERE email='miguelrevine@gmail.com') ORDER BY created_at DESC LIMIT 1;
   SELECT next_day, status FROM subscribers WHERE email='miguelrevine@gmail.com';
   -- tras abrir (sin confirmar) el enlace de unsubscribe:
   SELECT status FROM subscribers WHERE email='miguelrevine@gmail.com';  -- debe seguir 'active'
   ```

## Feature: cuentas de usuario (2026-07-17) — HECHA y verificada

Implementada siguiendo `accounts-design.md` en 5 bloques, cada uno commiteado por separado.

**Bloque 1 — esquema**: `password_hash`/`password_salt` en `subscribers`, tablas `sessions` y
`plan_equivalence` creadas. Verificado con `sqlite_master`/`PRAGMA table_info` en D1 remota.
Añadida también `login_attempts` (no está en accounts-design.md §1, pero hace falta para el
rate-limit de §3 — no hay binding de KV en este proyecto, así que uso D1 para eso).

**Bloque 2 — `precompute_equivalence.py`**: match de cobertura acumulada por tema (no regla de
tres). Ejecutado primero sobre 90/180/270 (1080 filas) y **reejecutado con los 4 planes juntos
en cuanto el 365 quedó limpio** → **2715 filas** en `plan_equivalence` (12 pares ordenados × sus
días). Muestra verificada en D1: **L1-90 día 30 → L1-270 día 95** (no 90, que sería la regla de
tres — confirma que el algoritmo usa cobertura real, no proporción de días). Verificado también
`COUNT(DISTINCT from_plan_id)=4` tras la reejecución.

**Bloque 3 — Worker**: `/api/signup`, `/api/login` (rate-limit 10/hora por email+IP, verificado:
6 fallos correctos + bloqueo en el 7º con 10 intentos acumulados), `/api/logout`, `GET
/api/account`, `/api/account/change-plan` (restart|resume), `/api/account/cancel`,
`/api/account/password`, `GET /api/admin/subscribers`. PBKDF2-SHA256 100k iteraciones (Web
Crypto, nunca bcrypt). Añadido `GET /api/account/plan-options` (no está en §3 literal, pero la
tarea 4 pide mostrar el resultado concreto ANTES de confirmar, y el endpoint de cambio de plan
por sí solo no puede previsualizar sin aplicar). `ADMIN_TOKEN` generado aleatorio y puesto como
secret — **te lo di una sola vez en el chat de esa sesión; si lo perdiste, pídeme que lo
regenere** (nunca queda en archivos/commits/logs).

**Bloque 4 — Frontend**: `site/login.html` (tabs login/signup), `site/account.html` (plan,
progreso, streak/precisión, cambio de plan con las DOS opciones concretas antes de confirmar —
"Start from scratch: pill 1 of N" vs "Keep my progress: pill X of N", cancelación con
confirmación en dos pasos sin diálogos nativos, cambio de contraseña, logout), `site/admin.html`
(token en memoria, nunca localStorage; tabla paginada sin datos de contraseña). Enlace "Log in"
añadido al nav de index.html.

**Bloque 5 — prueba de fuego**: hecha con una cuenta de prueba (`firetest2@daily-charter.com`,
plan 90), NO con el suscriptor real. Verificado end-to-end: signup con contraseña → login →
`GET /api/account` → adelanté `next_day` a 45 manualmente (SQL directo, solo para tener un caso
de prueba) → `plan-options` predijo **día 139 de 270** → `change-plan` modo `resume` aplicado →
**D1 confirma `next_day=139` exacto** → `cancel` → **D1 confirma `status='cancelled'`**. Cuenta de
prueba borrada al final (D1 solo tiene ya al suscriptor real).

⚠️ **Nota de testing**: al probar el flujo real haciendo clic en el navegador (Chrome vía
automatización), una extensión instalada en ese perfil (parece un wallet cripto) intercepta y
bloquea los fetch hacia `*.workers.dev`, dando 503/"Failed to fetch" tanto con `fetch` como con
`XMLHttpRequest` — confirmado que NO es un bug real: el mismo endpoint responde 200 sin problema
por curl en paralelo. La UI en sí quedó verificada visualmente (formularios, tabs, campos) y
funcionalmente por API; si vuelves a probarlo tú en un navegador limpio debería ir sin fricción.

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

## Generación 180/270/365 (2026-07-17) — CERRADA

- **90, 180, 270, 365**: los 4 generados, validados a 0 errores/0 avisos y **sembrados en D1
  remota**. `/api/plans` → `[90,180,270,365]`. Verificado con SQL: 4 filas en `plans`,
  **905 píldoras totales**.
- El 365 necesitó 8 rondas de `qa_loop.sh` (76→19→12→6→6→5→3→3 días) y quedó con 3 avisos
  residuales de títulos duplicados que el bucle automático no consiguió resolver solo
  (`qa_loop.sh` tiene tope de rondas). Se cerró con el mismo patrón manual que ya había funcionado
  en plan-90/180: `regen --avoid` nombrando el título exacto duplicado y el día que ya lo cubría,
  forzando un concepto distinto. Días 238/288/310 (duplicaban con 226/276/34) → **0 errores,
  0 avisos** en la validación final.
- Script `pill-factory/qa_loop.sh` (nuevo esta sesión): automatiza validar→regenerar (errores +
  duplicados + avisos)→repetir hasta limpio o agotar rondas. Úsalo así para futuros planes:
  `bash pill-factory/qa_loop.sh <days> <rondas>`. Si se agota el tope de rondas con solo
  duplicados de título restantes (no copia literal), el paso manual de arriba es el patrón a
  seguir.
- `plan_equivalence` reejecutada con los 4 planes juntos tras sembrar el 365 (ver bloque 2 de la
  feature de cuentas, arriba): 2715 filas, verificado.

## Auditoría externa (2026-07-17) — correcciones aplicadas

1. ✅ plan-90 sembrado en D1 remota (subscribe 201 verificado); `/api/plans` nuevo endpoint;
   selector de index deshabilita planes no sembrados ("Coming soon"); error 404 sin códigos internos.
2. ✅ Validación de email en cliente (checkValidity/reportValidity) **y en servidor** (regex, 400).
3. ✅ Botón "Start free" del nav: regla específica `.nav-links a.btn` conserva blanco (verificado
   estilo computado en las 3 páginas que lo llevan).
4. ✅ Quiz de muestra (index/archive): respuesta incorrecta muestra su porqué + revela la correcta
   con explicación y bloquea el quiz (verificado en navegador).
5. ✅ Legales rellenas (Daily Charter S.L., Calle García Treviño, España, 17-jul-2026, Stripe
   pendiente/Resend/GitHub/Cloudflare) y footer postal del email (plantilla + worker). Banner
   amarillo fuera; nota discreta "Pending legal review".
   ⚠ PENDIENTE DEL USUARIO: (a) periodo de retención sigue "[N] months" en privacy.html — no se
   me dio el número; (b) la dirección postal parece incompleta (sin número/CP/ciudad); (c) revisión
   por abogado de ambas páginas.
6. ✅ 404.html branded (servida por Pages, verificada en producción).
7. ✅ cfainstitute.org enlazado (única URL en texto plano).
8. ✅ Móvil 390px: sin overflow horizontal en las 10 páginas (test programático) + revisión visual
   de nav/hero/selector/checkout. Sin cambios necesarios.

## Extras de esta sesión

- `review.html` ahora es interactivo (plantilla `pill-factory/review_template.html`): quiz clicable
  con explicaciones, veredicto 👍/👎 + notas por píldora, progreso, export de feedback en markdown.
  Verificado en Chrome. Se sirve en http://localhost:8901/review.html mientras esta sesión viva.
- Subdominio workers.dev registrado: `miguelrevine.workers.dev` (vía API, wrangler v4 ya no tiene
  el comando `subdomain`).

## Qué necesito de ti

1. **Fase 8 (prueba de fuego original) sigue sin hacer**: nunca se envió la píldora 001 a
   `miguelrevine@gmail.com` (tabla `sends` vacía para ese suscriptor). Dime si quieres que la
   retome ahora — implica ajustar `send_hour_utc` y disparar el cron manualmente, y que confirmes
   la recepción, SPF/DKIM/DMARC en "Mostrar original" de Gmail, el botón B del email, y el
   unsubscribe, tal y como se definió originalmente.
2. Si perdiste el `ADMIN_TOKEN` que te di en el chat, dímelo y te genero uno nuevo (nunca queda
   guardado en ningún archivo del repo).
3. Nada urgente más: la feature de cuentas está completa y verificada; el 365 terminará de
   converger solo en background.
