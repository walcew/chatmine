"""Importar este pacote registra todos os providers embutidos.

Para adicionar um provider: crie `providers/<nome>/` com uma classe que satisfaça
`core.Provider`, chame `register(...)` na importação dela, e importe-a aqui.
"""

from . import mail, teams, whatsapp  # noqa: F401  (import com efeito colateral: registra os providers)
