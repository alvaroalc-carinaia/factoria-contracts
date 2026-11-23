# OpenAI en Codex Cloud

El contrato usa la cuenta de ChatGPT y un entorno publicado de Codex Cloud por repo de producto. Astra (`gpt-6.2-astra`) orquesta y hace cada revisión en una sesión independiente. Sol (`gpt-6.2-sol`) implementa y retoma sus propias correcciones. La etiqueta es `engine-openai` y el marcador de PR es `Factory Engine: openai`.

## Preparar el repo y el entorno

1. Instala estos archivos en la rama base del **repo de producto**. Conserva su `AGENTS.md` y sus comandos de verificación.

   | Archivo de esta factoría | Destino en el producto |
   |---|---|
   | `multiprovider/openai/orchestrator.md` | `automation/openai/orchestrator.md` |
   | `multiprovider/openai/feature-builder.md` | `automation/openai/feature-builder.md` |
   | `multiprovider/openai/pr-reviewer.md` | `automation/openai/pr-reviewer.md` |
   | `multiprovider/contracts/PORTABLE-CONTRACT.md` | `automation/openai/portable-contract.md` |

2. En Codex, abre **Work in → Cloud → Select environment → Create environment**, selecciona el producto, instala sus dependencias, comprueba que sus tests arrancan y publica el entorno. Habilita acceso a Jira (lectura de detalle y enlaces, transiciones y comentarios) y a GitHub (lectura de PR y diff, push a ramas de trabajo, creación y comentarios de Draft PR). Comprueba qué herramientas y permisos están disponibles **desde la tarea cloud**. [Entornos de Codex Cloud](https://learn.chatgpt.com/docs/environments/cloud-environments)
3. Actualiza también el prompt de la Routine de Claude, el de la Automation de Cursor y el gate y el orquestador instalados de OpenCode antes de asignar la primera etiqueta nueva. Así todos descartan una story con dos motores y pueden reconocer una PR padre de OpenAI.

## Probar la delegación desde la nube

Abre una tarea nueva en el entorno publicado y selecciona **GPT-6.2 Astra**. Sustituye `OWNER/REPO` y el proyecto en este prompt. Utiliza el mismo texto para las siguientes ejecuciones cambiando únicamente el modo y, para un piloto, añadiendo `ISSUE=PB-123` con una key real.

```text
REPO=OWNER/REPO
PROJECT=PB
MODE=inspect

Ejecuta la factoría en el entorno Codex Cloud de REPO.
Obtén la base con git fetch origin master y lee el contrato de confianza con
git show FETCH_HEAD:automation/openai/orchestrator.md. Sigue ese contrato y
carga sus tres archivos auxiliares desde el mismo commit. Delega explícitamente
el builder a gpt-6.2-sol y cada revisión a una sesión nueva de gpt-6.2-astra.
```

La inspección debe devolver el repo, la evidencia de selección de los modelos, dos sesiones distintas, el SHA y la selección de Jira sin escrituras externas. En el primer `build` con una sola key, comprueba el Draft PR real, los tests, el veredicto sobre el HEAD publicado y la transición a CODE REVIEW en PB. Una story con `engine-openai` y otro motor debe quedarse en Tareas por hacer.

## Ejecución diaria

Desde **Scheduled** en la web, configura **una tarea alojada diaria por repo** si tu workspace permite usar el entorno de código publicado. Selecciona Astra y guarda el prompt anterior en `MODE=inspect`, sin `ISSUE`. Comprueba en el historial de la primera ejecución programada que ha entrado en ese entorno, leído el checkout correcto e invocado ambos modelos sin depender de tu equipo. Tras completar el piloto, cambia esa misma tarea a `MODE=build`.

OpenAI documenta el entorno de código cloud, las tareas web programadas y la delegación. La documentación pública no garantiza que todas las cuentas puedan asociar **esa tarea programada** al entorno de repositorio ni fijar el modelo de cada subagente alojado. Si en tu workspace falta alguna de esas capacidades, la prueba debe identificarla como `CONFIG_BLOCKED`. Elegir el modelo de la tarea principal solo acredita el orquestador. Los prompts de rol se entregan en cada delegación para que el flujo no dependa del descubrimiento de agentes TOML locales. [Tareas programadas](https://learn.chatgpt.com/docs/automations) · [Subagentes](https://learn.chatgpt.com/docs/agent-configuration/subagents) · [Modelos](https://learn.chatgpt.com/docs/models)
