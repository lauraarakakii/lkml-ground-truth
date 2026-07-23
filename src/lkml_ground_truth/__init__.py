"""lkml-ground-truth: gera ground truth de patch->commit para a LKML.

Casa e-mails de patch de um dataset MailingListsHeritage/PaStA com commits
do repositório git do kernel Linux, reaproveitando o motor de comparação
do PaStA (:mod:`lkml_ground_truth.pasta`) e um índice arquivo->commits
construído em uma única passada sobre o histórico do repositório.
"""

__version__ = "0.1.0"
