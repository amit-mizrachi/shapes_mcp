from enrichment.column_enricher import ColumnEnricher
from enrichment.rules.date_enrichment_rule import DateEnrichmentRule
from enrichment.rules.name_concatenation_rule import NameConcatenationRule


def create_default_enricher() -> ColumnEnricher:
    return ColumnEnricher(rules=[
        DateEnrichmentRule(),
        NameConcatenationRule(),
    ])
