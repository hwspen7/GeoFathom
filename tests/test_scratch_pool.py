import numpy as np
import pytest
from geometry.buffers import ScratchPool

def test_bounded_reuse_zeroing_and_lifetime():
    with ScratchPool(4096) as pool:
        with pool.floats((16,16)) as a:
            assert a.dtype==np.float32
            a.fill(9)
            with pytest.raises(RuntimeError,match="active"):
                pool.close()
            with pytest.raises(MemoryError):
                with pool.floats((1024,)):
                    pass
        with pool.floats((16,16)) as b:
            assert np.count_nonzero(b)==0
        with pool.floats((1024,)) as c:
            assert np.count_nonzero(c)==0
    with pytest.raises(RuntimeError,match="closed"):
        with pool.floats((1,)):
            pass
