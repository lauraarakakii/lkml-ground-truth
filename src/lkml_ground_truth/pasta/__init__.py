"""Motor de comparação vendorizado do projeto PaStA (Patch Stack Analysis).

Copyright (c) OTH Regensburg, 2016-2020
Author: Ralf Ramsauer <ralf.ramsauer@oth-regensburg.de>
Licenciado sob os termos da GNU GPL, versão 2.

Este subpacote contém apenas o subconjunto do PaStA (`pypasta`) necessário
para comparar um patch de e-mail com um commit candidato: leitura de diff,
normalização de mensagem e o motor de similaridade (``patch_evaluation``).
Não inclui ``Clustering.py`` nem ``PatchStack.py``, que fazem parte de um
fluxo de trabalho diferente (clustering de patch stacks) e não são usados
por este projeto.

Os nomes de módulo foram normalizados para ``snake_case`` em relação ao
PaStA original para manter consistência com o restante do projeto; o
conteúdo e os cabeçalhos de copyright de cada arquivo foram preservados.
"""
