# Building instance refinement experiments

The validation-only study retains the selected flip baseline (50% fixed fusion, .35 threshold, adaptive seeds at 6 pixels), compares connected and watershed partitions, and measures conservative adjacency-based fragment merging. Hybrid views blend 65% flip and 35% multiscale probability while retaining flip-aligned auxiliary heads. The experiment never uses test rows or trains weights.

Run `python scripts/building_refinement_study.py --dataset DATASET --models PRIMARY SECONDARY --output REPORT.json --device cuda`. Reports include per-image overlap patterns, pixel/object/boundary scores, and validation-only temperature fits. The oracle-mask connected diagnostic is not a deployable algorithm or a theoretical upper bound. Fragment merging preserves all foreground and holes; it must be validated before deployment. No prior result is overwritten.

CUDA vision sessions and GPU acceptance profiling disable TF32 by default. The upstream mixed-precision DINO model is not automatically rewritten: use the independently hashed, locally converted FP32 derivative validated on the target host. Existing Windows library initialization remains unchanged; use the proven local DLL setup until it is independently qualified.
