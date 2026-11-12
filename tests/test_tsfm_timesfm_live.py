"""TimesFM 3.0 adapter (T16) canlı test — ağırlık HF cache'te varsa koşar.

addopts (`-m 'not live'`) bu testi normal koşumdan dışlar; `pytest -m live`
ile çağrılır. Ağırlık cache'te yoksa indirme DENEMEZ, atlar.
"""

import os

import numpy as np
import pytest
from tsfm_timesfm_araclari import TUF, agirlik_yerelde_mi, sonraki_ay, suruculu_kesit

from trnowcast.models.tsfm_timesfm import TIMESFM3_MV


@pytest.mark.live
def test_timesfm3_mv_live_tek_cikarim():
    if not agirlik_yerelde_mi("google/timesfm-3.0-pytorch"):
        pytest.skip("timesfm-3.0 ağırlığı HF cache'te yok — canlı test atlandı")
    # Bu test gerçek ağırlığı indirmez; HF hub'a çıkmayı da kapatarak yalnız
    # cache'ten yükler.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    kesit = suruculu_kesit(
        [float(i) + (0.3 if i % 2 else -0.3) for i in range(40)]
    )
    fp = TIMESFM3_MV(kesit, sonraki_ay(kesit), TUF)
    assert np.isfinite(fp.point)
    assert fp.lower <= fp.point <= fp.upper
