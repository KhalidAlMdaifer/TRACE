"""TRACE: tracking recordings via aircraft curve estimation."""
import os

# As dopplertrack's own CLI does, before numpy loads: one BLAS thread per process. The
# library parallelises with processes, and oversubscribed threads make every worker slower.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")
