"""Measure Ledgerlens on synthetic mailboxes whose right answers are known in advance.

- ``world``: a customer's dealings with its vendors, as plain data.
- ``synth``: invents a World from a seed and writes it out as a mailbox of ``.eml`` files.
- ``oracle``: works out from the World alone what an audit must find.
- ``score``: compares an audit's findings with the oracle's: precision, recall and dollars.
- ``runner``: generates, audits and scores many seeds, and writes the evaluation report.
"""
