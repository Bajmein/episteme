# Migración de OMEGA

[← Volver al README](../README.md)

```bash
d=$(mktemp -d)   # carpeta privada (0700), no una ruta fija de /tmp
omega export-obsidian --output-dir "$d/omega" --project fabrik --limit 1000
uv run scripts/migrate_omega.py --export "$d/omega/omega-memories" \
  --vault "$HOME/.episteme" --project fabrik \
  --omega-db ~/.omega/omega.db \
  --map-project /home/ana/src/fabrik=fabrik --dry-run
```

Haz todo en la misma shell (`d` no pasa de una shell a otra). Tras repetir el segundo comando sin `--dry-run`, borra el export con `rm -rf "$d"`.

Sin `--dry-run` escribe; `--dry-run` cuenta lo mismo que la ejecución real. Usa la misma validación y detección de duplicados que `remember`, así que una segunda ejecución no duplica nada. Qué hace con cada cosa:

- Se descartan los `checkpoint`, los `project_status`, los «Edit pattern…», las capturas automáticas de sesión y las reemplazadas en OMEGA.
- Se quitan los prefijos «fabrik (fecha):», «Decision:», «Lesson:» y «Assistant fix:». Del título (y por tanto del nombre del archivo) se quita además una etiqueta inicial entre corchetes, como `[MEMORIA GI - feedback]`; el cuerpo la conserva.
- Las etiquetas `dominio:x` pasan a `dominio/x`; las que son una ruta (`/…` o `C:\…`) pasan a `files`, relativas al proyecto; el resto se descarta. `helpful` queda en 0.
- Los tipos se traducen tal cual (`user_preference` → `preference`, `lesson_learned` → `lesson`…): OMEGA no distingue una preferencia de una decisión, así que conviene revisar las `preference` migradas y corregir el tipo con `revise(action="set", fields={"type": …})`, que mueve la nota a su carpeta.
- `source` lleva el id de OMEGA (`omega:mem-…`): una memoria con ese `source` ya en el vault no se vuelve a crear. Entre duplicados del export se queda el más reciente por fecha.
- `--omega-db` abre `omega.db` solo para lectura (`mode=ro`) y no toca nada de `~/.omega`. De ahí salen `priority` (el export no la trae) y los recordatorios: los `pending` pasan a `reminder` con `due` = `remind_at`; los `dismissed` no se migran.
- `--map-project VIEJO=NUEVO` (repetible) lleva proyectos de OMEGA, por nombre o ruta, a uno de episteme. Las rutas se comparan sin la barra final y, en Windows, sin distinguir mayúsculas ni `\` de `/`. Lo que no sea `--project` ni esté mapeado se omite, y la salida termina con `Proyectos omitidos: <proyecto> (n), …` para saber qué mapear. OMEGA suele guardar el mismo proyecto con el nombre y con la ruta; antes del ensayo, `select project, count(*) from memories group by project` sobre `omega.db` dice cuáles hay.
- Las memorias sin proyecto en OMEGA entran en `--project` (la salida dice cuántas, para revisarlas); `--unassigned skip` las omite.
