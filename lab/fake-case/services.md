# Örnek Bank synthetic service contract

All endpoints accept POST JSON. All listed request fields are required. Field and
endpoint names must be preserved exactly. Every response below is HTTP 200 JSON.
There is no products array: `/hesap-getir` returns one statement debt object.

| Endpoint | Purpose | Request fields | Response fields |
| --- | --- | --- | --- |
| /kimlik-dogrula | Verify one identity answer | customer_id: string; field: string enum [birth_year, postcode]; answer: string | verified: boolean |
| /hesap-getir | Read one customer's statement debt | customer_id: string | customer_id: string; statement_id: string; statement_debt: number; days_late: integer |
| /odeme-sozu-olustur | Record a confirmed payment promise | customer_id: string; statement_id: string; amount: number; date: string format date | success: boolean; promise_id: string |
| /not-ekle | Record a call note | customer_id: string; text: string; reason: string enum [refused, hardship] | success: boolean |
| /geri-arama | Schedule a callback | customer_id: string; date: string format date; time: string | success: boolean |
| /temsilciye-aktar | Transfer to a human agent | customer_id: string; queue: string enum [support, hardship] | success: boolean |
| /aramayi-bitir | Record and close the call | customer_id: string; outcome: string enum [promise, no_promise, callback, transferred]; reason: string | success: boolean |
