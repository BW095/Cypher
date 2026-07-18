"""Cypher evaluation harness — measures the system against the problem
statement's Evaluation Focus:

  * entity-extraction accuracy across document types
  * query answer quality on benchmark questions
  * knowledge-graph linkage completeness
  * time-to-answer versus a naive keyword baseline
  * compliance gap-detection accuracy

Run with:  python -m eval.run   (from the backend/ directory)
"""
