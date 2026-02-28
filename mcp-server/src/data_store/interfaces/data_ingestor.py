from __future__ import annotations

from abc import ABC, abstractmethod

from shared.modules.data.parsed_csv import ParsedCSV
from shared.modules.data.table_schema import TableSchema


class DataIngestor(ABC):
    @abstractmethod
    def ingest(self, parsed_csv: ParsedCSV) -> TableSchema: ...
