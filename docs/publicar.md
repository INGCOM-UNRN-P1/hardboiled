# Publicar una versión en PyPI

hardboiled se publica con [Trusted Publishing](https://docs.pypi.org/trusted-publishers/):
GitHub Actions se autentica en PyPI con OIDC, sin tokens guardados.

## Configuración (una sola vez)

1. Subir el repositorio a GitHub.
2. En PyPI, *Your projects → Publishing → Add a new pending publisher*:
   - PyPI project name: `hardboiled` (libre al momento de preparar esto)
   - Owner / Repository: los del repositorio en GitHub
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
3. En GitHub, *Settings → Environments → New environment* llamado `pypi`
   (conviene exigir una aprobación manual).

## Cada versión

1. Actualizar `version` en `pyproject.toml` y hacer commit
   (`chore(release): vX.Y.Z`).
2. Crear y empujar el tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. El workflow verifica que el tag coincida con la versión, repite la prueba
   de instalación como `uv tool` (`scripts/smoke_install.py`), construye sdist
   y wheel y los publica.

Después de publicar:

```bash
uvx hardboiled doctor                      # sin instalar nada
uv tool install "hardboiled[zig]"          # instalación permanente
uv tool upgrade hardboiled                 # actualizar
```

Mientras no esté en PyPI se puede instalar desde el repositorio:

```bash
uv tool install "hardboiled[zig] @ git+https://github.com/USUARIO/hardboiled"
```
