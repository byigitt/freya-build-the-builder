# Deneme Bank servis sözleşmesi — 21 Ekim 2026

Tüm uç noktalar POST, Content-Type application/json. Tüm istek alanları aksi söylenmedikçe zorunludur. Başarılı HTTP 200 yanıt gövdesi aşağıdaki tam JSON biçimindedir; ek data sarmalayıcısı veya products dizisi YOKTUR. Kimlik ve borç alanları sadece test içindir. Tüm parasal alanlar JSON number, gün sayıları integer; diğer alanlar belirtilen türdedir.

## POST /kimlik-dogrula
Müşterinin kimliğini kontrol eder. İstek: {"musteri_no":"DN001","tckn_son_dort":"1357","dogum_tarihi":"1988-04-12"}. Üç alan string; tckn_son_dort tam dört rakam, doğum tarihi ISO YYYY-MM-DD. Yanıt: {"dogrulandi":true,"kalan_hak":1}. dogrulandi boolean, kalan_hak integer. Yanlış kimlikte dogrulandi false döner.

## POST /ekstre-getir
Yalnızca doğrulama sonrası müşterinin TEK kredi kartı ekstre hesabını getirir. İstek: {"musteri_no":"DN001"}. Yanıt: {"hesap_no":"H001","card_last4":"2468","statement_amount":2400.0,"minimum_payment":600.0,"due_date":"2026-10-20","days_overdue":8}. hesap_no ve card_last4 string, statement_amount ve minimum_payment number, due_date ISO tarih string, days_overdue integer. Hesap türü sabit kredi kartıdır; yanıt içinde type veya ürün dizisi bulunmaz. Ekstre borcu tam tutar, minimum_payment söz için alt sınırdır.

## POST /odeme-sozu-kaydet
Tek hesaba onaylanmış ödeme sözünü yazar. İstek: {"musteri_no":"DN001","hesap_no":"H001","soz_tutari":600.0,"soz_tarihi":"2026-10-30"}. soz_tutari number, diğerleri string. Yanıt: {"basarili":true,"soz_no":"S001"}. basarili boolean, soz_no string. basarili false ise söz kaydedilmemiştir.

## POST /gorusme-notu-ekle
Görüşme açıklamasını kaydeder. İstek: {"musteri_no":"DN001","not_metni":"Müşteri ödeme yaptığını bildirdi."}. Yanıt: {"basarili":true}. Tüm istek alanları string, basarili boolean.

## POST /geri-arama-planla
Geri arama randevusu oluşturur. İstek: {"musteri_no":"DN001","geri_arama_zamani":"2026-10-30T10:30:00+03:00","neden":"uygun_degil"}. Tüm alanlar string; zaman ISO-8601 Europe/Istanbul ofsetlidir. Yanıt: {"basarili":true,"randevu_no":"R001"}; basarili boolean, randevu_no string.

## POST /temsilciye-aktar
Canlı insan temsilciye aktarır. İstek: {"musteri_no":"DN001","neden":"maddi_gucluk"}. neden enum: maddi_gucluk, itiraz, musteri_talebi, kayit_itirazi, hesap_hatasi, uygun_tarih_yok. Yanıt: {"basarili":true}. basarili boolean.

## POST /gorusmeyi-kapat
Sonucu kaydeder ve görüşmeyi bitirir. İstek: {"musteri_no":"DN001","sonuc":"odeme_sozu_alindi","neden":"bos"}. sonuc enum: odeme_sozu_alindi, soz_alinamadi, kimlik_dogrulanamadi, ucuncu_kisi, temsilciye_aktarildi, odeme_bildirildi, geri_arama_planlandi, borc_yok. neden string; geçerli iş nedenleri: bos, odemeyi_reddetti, maddi_gucluk, itiraz, musteri_talebi, kayit_itirazi, hesap_hatasi, uygun_tarih_yok, uygun_degil, kimlik_hatasi, kimlik_reddi. Yanıt: {"basarili":true}. basarili boolean.
