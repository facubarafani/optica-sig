"""Bulk import and export of spreadsheets.

Layered on purpose:
  readers.py     file bytes -> (headers, rows)      [the only format-aware code]
  specs.py       what each target accepts           [declarative, shared]
  engine.py      analyze() / commit()               [validation + business rules]
  templates.py   spec       -> blank .xlsx template
  exporters.py   data       -> .xlsx / .csv         [mirror of engine.py]

Import and export both read ``specs.py``, which is what makes a file round-trip:
export the catalogue, edit it in Excel, upload it again and rows match by key.
"""
from app.services.importer import engine, exporters, readers, specs, templates

__all__ = ["engine", "exporters", "readers", "specs", "templates"]
