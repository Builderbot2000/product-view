"""The embedding pipeline as it stood before commit 25d794f, restored for the
pre-LLM upgrade trials (llm-trials.md, "Embedding route: upgrade trials").

Files are `git show 25d794f^:src/product_view/{cluster,embed}/<name>.py`, unchanged
except for imports:

- encoder.py: `..lang.translate` -> `product_view.lang.translate`
- pipeline.py: `..embed` -> `.`; `..store.Store` -> the current `product_view.store.Store`,
  which no longer has the old `load_segments` / `save_run`, so `pipeline.run()` is kept
  for reference only. `trials/prellm/harness.py` reproduces its clustering path step by
  step from the same functions (units.build, vague.vague_mask, graph.build_knn,
  strategies.LeidenStrategy, granularity.search/filter_clusters, synthesize.ctfidf and
  synthesize.sentence_title).
"""
