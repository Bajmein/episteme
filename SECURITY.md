# Política de seguridad

## Versiones con soporte

Solo el último tag publicado.

## Cómo reportar una vulnerabilidad

Usa «Report a vulnerability» en la pestaña Security del repositorio (reporte privado). No abras un issue público ni pegues notas del vault, memorias o credenciales.

La respuesta es de mejor esfuerzo: es un proyecto personal y no hay plazo garantizado.

## Modelo de amenaza

episteme es un servidor local que habla por stdio y no usa la red. El vault y su `episteme.toml` son de confianza: quien puede escribir en ellos ya controla el servidor. Lo que se considera una vulnerabilidad es lo que permite a una entrada no confiable (el contenido de una nota o de una memoria, o los argumentos de un tool) salirse de ese marco.

## Riesgos aceptados

- **Una memoria guardada vuelve al contexto.** Lo que el agente guarda con `remember`, `revise` o `checkpoint` se entrega después en `context` y `search`. No se restringen `priority=5` ni `project="_shared"`: el uso normal depende de que el agente guarde normas y memorias compartidas. El freno es que esos tres tools quedan en «ask» en los permisos que instala `/episteme:setup`.
- **El filtro de credenciales es de mejor esfuerzo.** Evita guardar los formatos más comunes, no todos los de todos los proveedores.
- **Los `deny` de la skill no son un aislamiento.** Reducen errores del agente; no sustituyen a un sandbox.
- **El `episteme.toml` de un vault es configuración de confianza**, incluida `backup.dir`. No abras con episteme un vault de origen desconocido.

## Runner propio del CI

El CI de Linux corre en un runner propio. Los PR de forks y de Dependabot se desvían a `ubuntu-latest`, ningún job del runner propio usa secretos ni publica artefactos, y los workflows de colaboradores externos exigen aprobación manual: no se aprueba la ejecución de un PR que toca `.github/` sin leerlo entero.
