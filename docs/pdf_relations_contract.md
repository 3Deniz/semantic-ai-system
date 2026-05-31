# PDF Ingestion and Space Relations Contract (Faz 0)

Durum: frozen-v1
Tarih: 2026-05-24

Bu dokuman, PDF ingest ve tum space iliski sorgusu icin uygulanacak ilk kontrati tanimlar.

## 1) Scope

### 1.1 In-scope
- Tek PDF ingest: `POST /ingest/pdf`
- Coklu PDF ingest: `POST /ingest/pdfs` (batch)
- Varsayilan candidate-asamasi ile staged ingestion
- Provenance standartlari (page/paragraph/sentence/chunk)
- Cagri bazli iliski gorunumu: `GET /semantic/relations`

### 1.2 Out-of-scope (v1)
- OCR (scan PDF) destegi
- PDF tablo/sekil semantik cikarma
- Dis sistemlerde distributed storage

## 2) Limits and Defaults

- Desteklenen dil: `tr`, `en` (free-text parser kural bazli oldugu icin best-effort)
- Varsayilan stage: `candidate`
- Max tek dosya boyutu: `20 MB`
- Max batch dosya sayisi: `10`
- Max batch toplam boyut: `100 MB`
- Varsayilan relations max_depth: `2`
- Varsayilan relations max_edges: `300`

## 3) Provenance Schema (frozen)

Her ciktilan triple/candidate kaydinda `provenance` icinde su alanlar desteklenir:

```json
{
  "source_document": "report_q2_2026.pdf",
  "source_type": "pdf",
  "ingestion_run_id": "run_01J0ABCXYZ",
  "page_index": 3,
  "paragraph_index": 2,
  "sentence_index": 1,
  "chunk_id": "p3_pg2_s1",
  "stage": "candidate",
  "source_text": "rain causes flood",
  "extraction_method": "rule_based_free_text"
}
```

Kurallar:
- `source_type` PDF ingest icin her zaman `pdf`.
- Tum indeksler `0-based`.
- `chunk_id` deterministic format: `p{page_index}_pg{paragraph_index}_s{sentence_index}`.
- `ingestion_run_id` tek ingest istegi boyunca sabit.

## 4) API Contracts

## 4.1 POST /ingest/pdf

Istek (multipart/form-data):
- `file`: PDF dosyasi (zorunlu)
- `source_document`: string (opsiyonel; yoksa dosya adi)
- `stage`: `candidate | validated` (opsiyonel; default `candidate`)
- `metadata`: JSON string (opsiyonel)

Basarili cevap (`200`):

```json
{
  "documents": 1,
  "pages": 12,
  "sentences": 186,
  "triples": 47,
  "candidates": 133,
  "candidate_ids": ["..."],
  "skipped": 6,
  "failed": 0,
  "ingestion_run_id": "run_01J0ABCXYZ",
  "source_document": "report_q2_2026.pdf"
}
```

Hatalar:
- `400`: invalid form/body
- `403`: auth failure (X-API-Key)
- `413`: dosya limiti asildi
- `415`: unsupported media type
- `422`: parse/extraction failure

## 4.2 POST /ingest/pdfs

Istek (multipart/form-data):
- `files`: birden cok PDF
- `stage`, `metadata` opsiyonel

Cevap (`200`):

```json
{
  "documents": 4,
  "pages": 61,
  "sentences": 803,
  "triples": 212,
  "candidates": 591,
  "candidate_ids": ["..."],
  "skipped": 23,
  "failed": 1,
  "failed_documents": [
    {"name": "broken.pdf", "error": "parse_failure"}
  ]
}
```

## 4.3 GET /semantic/relations

Query params:
- `query`: string (opsiyonel)
- `state`: string (opsiyonel)
- `include_spaces`: csv list, default `risk,goal,memory,attention,self,semantic`
- `max_depth`: int, default `2`, min `1`, max `4`
- `max_edges`: int, default `300`, min `50`, max `1000`

Kural:
- `query` veya `state` alanlarindan en az biri zorunlu.

Cevap (`200`):

```json
{
  "query": "flood",
  "state": null,
  "spaces": ["risk", "goal", "memory", "attention", "self", "semantic"],
  "nodes": [
    {"id": "entity:flood", "type": "entity", "label": "flood"},
    {"id": "space:risk", "type": "space", "label": "risk"}
  ],
  "edges": [
    {
      "source": "entity:flood",
      "target": "entity:damage",
      "space": "semantic",
      "relation_type": "causes",
      "confidence": 0.75,
      "provenance": {
        "source_document": "report_q2_2026.pdf",
        "page_index": 3,
        "sentence_index": 1,
        "review_status": "approved"
      }
    }
  ],
  "meta": {
    "max_depth": 2,
    "max_edges": 300,
    "generated_at": 1770000000.0
  }
}
```

## 5) Relation Graph Semantics

Node tipleri:
- `entity`: KG/TMS varliklari
- `state`: state tokenlari
- `space`: risk/goal/memory/attention/self/semantic

Edge alanlari:
- `space`: edge'in geldigi space
- `relation_type`: semantic relation veya derived relation (`supports`, `similar_to`, `salient_for`)
- `confidence`: `[0.0, 1.0]`
- `provenance`: kaynak izlenebilirlik bilgisi

## 6) Success Criteria (Faz 0 signed)

Asagidaki kosullar Faz 0 cikti kriteri olarak dondurulmustur:
- PDF dosyasi verilebiliyor ve ingest pipeline'a giriyor.
- Cikarilan bilgiler candidate queue'ya provenance ile dusuyor.
- Promote sonrasi ayni veri KG/TMS tarafinda aktif belief olarak gorunuyor.
- `GET /semantic/relations` cagrisinda tum secili space iliskileri tek cevapta donuyor.

## 7) Implementation Notes

- Mevcut `core/data_loader.py` candidate/promote/reject akisina uyum korunacak.
- Mevcut `core/parser.py` context merge davranisi provenance map ile kullanilacak.
- Mevcut `cognition/multispace_embedding.py` space siniflari relation ciktilarinda source olarak islenecek.
- v1 icin OCR yok; scan PDF'ler `422` veya `skipped` ile raporlanacak.
