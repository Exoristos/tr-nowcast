"""Paket iskeleti duman testleri: import edilebilirlik ve CLI grup davranışı."""

import sys

import pytest

import trnowcast
from trnowcast.cli import main


def test_paket_import_edilebilir():
    assert trnowcast.__name__ == "trnowcast"


def test_main_argumansiz_yardim_gosterir_ve_exit_0(capsys, monkeypatch):
    # T7 ile main, fetch/status/quality alt komutları olan bir click grubudur;
    # argümansız çağrı yardım metnini basıp exit 0 döner.
    monkeypatch.setattr(sys, "argv", ["trnowcast"])
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 0
    cikti = capsys.readouterr().out
    for komut in ("fetch", "status", "quality"):
        assert komut in cikti
