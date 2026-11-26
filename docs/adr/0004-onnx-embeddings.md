# Embeddings run on onnxruntime, not sentence-transformers

`sentence-transformers` hard-depends on torch, scipy, scikit-learn and sympy —
about 650 MB installed, roughly 85% of the environment — to run one 384-dim
encoder. `intfloat/multilingual-e5-small` ships its own fp32 ONNX export
(`onnx/model.onnx` + `onnx/tokenizer.json`), so `vectors.E5OnnxModel` runs it
directly with `onnxruntime` + `tokenizers` + `huggingface-hub` (~80 MB).

## Considered Options

- **sentence-transformers `backend="onnx"`.** Rejected: it still requires torch.
- **fastembed.** Rejected: it has no `multilingual-e5-small`, only `-large`
  (1024-dim, 2.2 GB), and its built-in ONNX path pools the CLS token, which is
  wrong for e5.
- **Quantized `model_qint8_avx512_vnni.onnx` (118 MB).** Rejected: it shifts
  scores, and is tuned for x86 AVX-512, which Apple Silicon lacks. The model
  lives in the `data/model-cache` volume, not the image, so its size doesn't
  count against the install.

## Consequences

- What sentence-transformers did implicitly is now our code: 512-token
  truncation, padding, mean pooling over the attention mask, L2 normalisation
  (the model's `modules.json` is Transformer → mean Pooling → Normalize). The
  e5 `query: ` / `passage: ` prefixes were already ours.
- Verified at the switch: cosine similarity 1.000000 (min, 6 d.p.) against
  sentence-transformers on 51 passages and 5 queries, and identical top-5
  results on the existing copter index.
- Stores built before the switch should be rebuilt with
  `ardupilot-refresh --all --build-vectors`. The old sentence-transformers
  files in `data/model-cache/models--intfloat--multilingual-e5-small` aren't
  used any more (only `onnx/` is fetched now) and can be deleted.
- Don't re-add sentence-transformers for convenience: it brings torch back.
