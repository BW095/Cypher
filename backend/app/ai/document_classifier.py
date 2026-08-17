"""
Document Classifier
===================
Lightweight, heuristic keyword classifier that auto-detects whether a document
belongs to the *industrial* or *government* domain and, for government docs,
which fine-grained category applies (invoice / contract / certificate / form).

Design principles
-----------------
- **No LLM calls** — classification is done purely from the filename and the
  first ``SAMPLE_CHARS`` characters of extracted text so it adds negligible
  latency to the ingestion pipeline.
- **Additive** — existing industrial documents pass through unchanged; only
  documents that match government keyword signals are re-labelled.
- **Single entry point** — call ``DocumentClassifier.classify(doc)`` and it
  returns the same ``CanonicalDocument`` object with ``doc_domain`` and
  ``doc_category`` filled in.  The EntityExtractor reads those fields to pick
  the right extraction prompt.

Extending
---------
Add or tune keyword sets in the ``_SIGNALS`` dict.  Each key is a
``DocCategory`` string; its value is a list of lowercase keyword/phrase
fragments that are searched with ``in`` against the normalised sample text.
Threshold scoring means a category wins only when it accumulates enough hits
so that a single incidental mention doesn't misclassify a document.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ingestion.canonical_document import CanonicalDocument

# How many characters from the start of the extracted text to inspect.
# Large enough to cover a typical header / preamble, small enough to be fast.
_SAMPLE_CHARS: int = 1500

# ---------------------------------------------------------------------------
# Keyword signals
# ---------------------------------------------------------------------------
# Each entry: category → list of (signal_phrase, weight) tuples.
# Weight lets strong unambiguous markers count more than generic words.
# A category wins when its cumulative weight reaches _THRESHOLD.
_THRESHOLD: float = 2.0

_SIGNALS: dict[str, list[tuple[str, float]]] = {
    "invoice": [
        ("invoice no", 3.0),
        ("invoice number", 3.0),
        ("tax invoice", 3.0),
        ("bill to", 2.5),
        ("bill of supply", 2.5),
        ("amount due", 2.0),
        ("total payable", 2.0),
        ("gst no", 1.5),
        ("gstin", 1.5),
        ("hsn code", 1.5),
        ("igst", 1.0),
        ("cgst", 1.0),
        ("sgst", 1.0),
        ("payment due", 1.5),
        ("purchase order", 1.0),
        ("p.o. no", 1.5),
        ("proforma invoice", 3.0),
        ("e-invoice", 2.0),
        ("irn", 1.0),
        ("unit price", 1.0),
        ("qty", 0.5),
    ],
    "contract": [
        ("this agreement", 3.0),
        ("agreement is entered", 2.5),
        ("party of the first part", 3.0),
        ("party of the second part", 3.0),
        ("hereinafter referred to as", 2.5),
        ("hereinafter called", 2.0),
        ("whereas", 1.0),
        ("terms and conditions", 1.5),
        ("indemnity", 1.5),
        ("governing law", 2.0),
        ("jurisdiction", 1.0),
        ("force majeure", 2.0),
        ("liquidated damages", 2.0),
        ("non-disclosure", 2.0),
        ("confidentiality", 1.0),
        ("in witness whereof", 2.5),
        ("signed and sealed", 2.0),
        ("memorandum of understanding", 3.0),
        ("mou", 1.0),
        ("service level agreement", 2.5),
        ("scope of work", 1.0),
    ],
    "certificate": [
        ("this is to certify", 3.0),
        ("certificate of", 2.5),
        ("certified that", 2.5),
        ("is hereby awarded", 2.5),
        ("is hereby certified", 2.5),
        ("certificate number", 2.0),
        ("validity:", 1.5),
        ("valid from", 1.5),
        ("valid until", 1.5),
        ("expiry date", 1.0),
        ("issuing authority", 2.0),
        ("authorized signatory", 2.0),
        ("seal of", 1.5),
        ("registration certificate", 2.5),
        ("compliance certificate", 2.5),
        ("no objection certificate", 3.0),
        ("noc", 1.0),
        ("calibration certificate", 2.5),
        ("gst registration", 2.0),
        ("pan card", 1.5),
        ("udyam registration", 2.5),
    ],
    "form": [
        ("application form", 3.0),
        ("form no.", 2.5),
        ("form no:", 2.5),
        ("please fill", 2.0),
        ("to be filled", 1.5),
        ("affix photograph", 2.5),
        ("signature of applicant", 2.5),
        ("declaration by applicant", 2.0),
        ("date of birth", 1.5),
        ("father's name", 1.5),
        ("mother's name", 1.5),
        ("aadhaar", 1.5),
        ("pan no", 1.5),
        ("mobile no", 0.5),
        ("for office use only", 2.0),
        ("self attested", 1.5),
        ("tick as applicable", 2.0),
        ("enclosures:", 1.0),
        ("undertaking", 1.0),
        ("nomination form", 2.5),
        ("challan", 1.5),
    ],
}

# Filename-stem hints that raise a category's score before text is inspected.
_FILENAME_HINTS: dict[str, list[tuple[str, float]]] = {
    "invoice": [("invoice", 3.0), ("inv_", 2.0), ("bill", 1.5), ("receipt", 1.0)],
    "contract": [("contract", 3.0), ("agreement", 2.5), ("mou", 2.5), ("sla", 2.0)],
    "certificate": [("certif", 3.0), ("noc", 2.5), ("licence", 2.0), ("license", 2.0)],
    "form": [("form", 2.5), ("application", 1.5), ("challan", 2.0)],
}


class DocumentClassifier:
    """Heuristic document classifier.  Instantiate once, call ``classify()``
    repeatedly — the object is stateless between calls.
    """

    @staticmethod
    def classify(doc: "CanonicalDocument") -> "CanonicalDocument":
        """Detect domain and category, mutate ``doc`` in place, return it.

        The method is safe to call even when ``doc.text`` is empty; in that
        case the document retains the default industrial/general labels.
        """
        sample = _normalise(doc.text[:_SAMPLE_CHARS])
        filename_stem = os.path.splitext(os.path.basename(doc.file_path))[0].lower()

        scores: dict[str, float] = {cat: 0.0 for cat in _SIGNALS}

        # --- Filename signals (fast, checked first) -------------------------
        for cat, hints in _FILENAME_HINTS.items():
            for phrase, weight in hints:
                if phrase in filename_stem:
                    scores[cat] += weight

        # --- Text signals ---------------------------------------------------
        if sample:
            for cat, signals in _SIGNALS.items():
                for phrase, weight in signals:
                    if phrase in sample:
                        scores[cat] += weight

        # --- Determine winner -----------------------------------------------
        best_cat = max(scores, key=lambda c: scores[c])
        best_score = scores[best_cat]

        if best_score >= _THRESHOLD:
            doc.doc_domain = "government"
            doc.doc_category = best_cat  # type: ignore[assignment]
            print(
                f"  [Classifier] '{os.path.basename(doc.file_path)}' → "
                f"government/{best_cat} (score {best_score:.1f})"
            )
        else:
            doc.doc_domain = "industrial"
            doc.doc_category = "general"
            print(
                f"  [Classifier] '{os.path.basename(doc.file_path)}' → "
                f"industrial/general (top score {best_score:.1f}, below threshold)"
            )

        # Persist classification into the document's metadata so it is stored
        # in Neo4j alongside the Document node for later querying.
        doc.metadata["doc_domain"] = doc.doc_domain
        doc.metadata["doc_category"] = doc.doc_category

        return doc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lower-case, collapse whitespace, strip punctuation noise for matching."""
    if not text:
        return ""
    s = text.lower()
    # Collapse any run of whitespace (tabs, newlines, multiple spaces) to a
    # single space so multi-word phrases match even when split across lines.
    s = re.sub(r"\s+", " ", s)
    return s.strip()
