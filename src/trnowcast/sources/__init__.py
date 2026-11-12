"""Veri kaynak modülleri (fred, fao, tuik, evds, survey).

Her kaynak modülü aynı long format arayüzünü üretir (date, value, series_id) ve
beklenmedik durumda (ağ hatası, beklenmedik şema) aşağıdaki SourceError'ı fırlatır;
sessizce boş DataFrame döndürmez.
"""


class SourceError(Exception):
    """Kaynak çekimi başarısız: ağ hatası veya beklenmedik yanıt şeması."""
