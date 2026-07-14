# INSTRUCCIONES — poner a trabajar a Claude Code

## 0 · Dónde dejar los archivos

1. Descomprime `dailycharter-project.zip` donde quieras tenerlo, por ejemplo:
   - Mac/Linux: `~/Proyectos/dailycharter`
   - Windows:   `C:\Proyectos\dailycharter`
2. **Copia tus 5 PDFs del temario a `pill-factory/pdfs/`** (la carpeta ya
   existe, vacía). No los subas nunca a GitHub: son material con copyright.
3. Abre una terminal EN ESA CARPETA y lanza `claude` (Claude Code).
   Al arrancar leerá solo el `CLAUDE.md` de la raíz y ya sabrá qué es el
   proyecto, cómo funciona y qué reglas no puede romper.

A partir de aquí, pégale los prompts de abajo **uno por uno, en orden**.
Cada fase termina con algo verificable antes de pasar a la siguiente.

---

## Fase 1 · Comprobar el entorno

> Comprueba mi entorno para este proyecto: versiones de python3, pip, git,
> node, npm; si están instalados wrangler, gh y ollama; y si el servidor de
> Ollama responde en localhost:11434 con algún modelo descargado. Instala con
> pip lo que falte de `pypdf requests`. Dame una tabla de qué está OK y qué
> falta con el comando exacto para instalarlo, pero no instales nada de
> sistema sin preguntarme.

## Fase 2 · Repos y despliegue de la web

> Inicializa git en la raíz del proyecto con un .gitignore que excluya
> pill-factory/pdfs/, *.partial, __pycache__, node_modules y .wrangler.
> Haz el primer commit. Después despliega la carpeta site/ en GitHub Pages
> (puedes apoyarte en site/deploy-github.sh o hacerlo tú con gh). Cuando
> termine, dame la URL pública y comprueba con curl que responde 200.

## Fase 3 · Piloto de contenido (plan de 90)

> Verifica con `pill_factory.py scan` que los 5 PDFs de pill-factory/pdfs/
> se mapean a sus temas. Luego lanza la generación del plan de 90 días con
> el mejor modelo que tenga descargado mi Ollama. Ve informándome del
> progreso cada ~15 píldoras. Si el proceso se corta, retómalo (hay
> checkpoints automáticos).

## Fase 4 · Control de calidad

> Valida el plan generado con validate_plan.py pasando --pdf-dir y
> --review 10. Si el chequeo de originalidad marca píldoras con solape
> literal con la fuente, regenera SOLO esas píldoras y vuelve a validar
> hasta que salga limpio. Después abre review.html (o dime la ruta) para
> que yo lea las 10 píldoras y te dé el visto bueno de calidad.

⚠️ Este paso es tuyo: lee las 10 píldoras. Si la calidad no te convence,
dile: «La calidad no me convence por X; prueba con [modelo mayor] /
baja la temperatura a 0.5 / añade al prompt que incluya un ejemplo
numérico en cada concepto» y repite las fases 3–4.

## Fase 5 · Generación completa (noche)

> La calidad del piloto está aprobada. Lanza en secuencia la generación de
> los planes de 180, 270 y 365 días con el mismo modelo. Al acabar cada uno,
> valídalo con --pdf-dir y arregla lo que marque. Déjame un resumen final
> con píldoras totales, avisos y tiempo empleado. (Voy a dejar el ordenador
> encendido toda la noche.)

## Fase 6 · Motor de emails (Cloudflare)

> Vamos a desplegar mail-engine/. Guíame para: crear cuenta/login de
> Cloudflare con wrangler, crear la base D1 "dailycharter", poner su id en
> wrangler.toml, aplicar schema.sql, generar los seed-*.sql con seed_plan.py
> y aplicarlos a D1, configurar los secrets TOKEN_SECRET (génerame uno
> aleatorio largo) y ESP_API_KEY (te lo pegaré yo de Resend), rellenar
> SITE_URL/FROM_EMAIL en wrangler.toml y hacer wrangler deploy. Al final
> verifica /health con curl.

Antes de esta fase crea tú la cuenta en https://resend.com (gratis),
verifica tu dominio con los DNS que te den (SPF/DKIM) y ten a mano la
API key para pegársela cuando te la pida.

## Fase 7 · Cablear web ↔ motor

> Con la URL del Worker desplegado: ponla en `var WORKER_URL` de
> site/index.html y en `var API_BASE` de site/quiz.html; en quiz.html
> elimina el objeto DEMO y descomenta el fetch de producción tal y como
> indican los comentarios del propio archivo. Commit y redespliega la web.

## Fase 8 · Prueba de fuego

> Prueba el sistema completo conmigo: (1) alta con mi email real desde el
> formulario de la web en el plan de 90; (2) dispara el cron manualmente
> con wrangler dev --test-scheduled y el curl a /__scheduled para que me
> llegue la píldora 001 ya; (3) cuando confirme que la he recibido,
> comprobamos que el botón B del email abre quiz.html, registra el intento
> en la tabla attempts de D1 y que next_day ha avanzado a 2. Lista los
> comandos de verificación en D1 y ejecútalos.

## Fase 9 · Lo que queda (cuando quieras)

- Stripe en site/checkout.html (las notas de integración están dentro del
  archivo) — hasta entonces el plan de pago no cobra.
- Revisión legal real de privacy.html y terms.html (tienen huecos
  [ENTRE CORCHETES] a propósito).
- Cron del recap dominical (el diseño está en backend-quiz-spec.md §4).

---

## Consejos de uso de Claude Code

- Pídele siempre que **verifique** lo que hace (curl, consultas a D1, tests).
- Si algo falla, pega el error tal cual: lo diagnostica mejor que un resumen.
- Puedes decirle «explícame qué vas a hacer antes de ejecutarlo» en los pasos
  delicados (deploy, secrets).
- Las fases 3 y 5 son largas: puedes cerrar Claude Code y retomar; la
  generación tiene checkpoints y el comando `generate` reanuda solo.
