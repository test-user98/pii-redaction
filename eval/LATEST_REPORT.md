# PII eval report

pred: `/Users/jaisipani/Desktop/scale/out/7248a14208cdae3f/spans.csv`  
truth: `/Users/jaisipani/Desktop/scale/eval/ground_truth/rhp_pages.csv`  
pages: 1, 2, 3, 4, 5, 6, 110, 111, 112, 114, 115, 116, 128

## Per type

| type | TP | FP | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|
| ADDRESS | 26 | 2 | 2 | 0.929 | 0.929 | 0.929 |
| DIN | 8 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| DOB | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| EMAIL | 30 | 1 | 1 | 0.968 | 0.968 | 0.968 |
| ORG | 51 | 6 | 3 | 0.895 | 0.944 | 0.919 |
| PAN | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| PERSON | 55 | 2 | 0 | 0.965 | 1.000 | 0.982 |
| PHONE | 20 | 0 | 1 | 1.000 | 0.952 | 0.976 |
| **micro** | 192 | 11 | 7 | 0.946 | 0.965 | 0.955 |

Token accuracy: **0.9836** (5225/5312 tokens); pages without extractable text skipped: [128]

## Misses (FN)

| page | text | type | reason |
|---|---|---|---|
| 6 | Link Intime India Private Limited | ORG |  |
| 114 | ICICI Venture House | ADDRESS |  |
| 116 | Link Intime India Private Limited | ORG |  |
| 116 | HDFC Bank Limited | ORG |  |
| 128 | 4th Floor, Mantri Sterling, Plot No. 341, Survey No. 997/8, Model Colony, Near Deep Bungalow Chowk, Pune - 411 016 | ADDRESS |  |
| 128 | 91-20-2721 8081 | PHONE |  |
| 128 | tininfo@nsdl.co.in | EMAIL |  |

## False hits (FP)

| page | text | type | reason |
|---|---|---|---|
| 4 | nuvama iICICI Securities | ORG |  |
| 5 | FINANCIAL EXPRESS | ORG |  |
| 5 | nuvama iICICI Securities G | ORG |  |
| 6 | ICICI Venture House | ORG |  |
| 110 | PCNTDA Green Building Block A 1st and 2nd floor Near Akurdi Railway Station Akurdi, Pune – 411 044 Maharashtra, India | ADDRESS |  |
| 112 | ICICI Venture House | ORG |  |
| 112 | Appasaheb Marathe | PERSON |  |
| 114 | ICICI Venture House | ORG |  |
| 128 | Visha Simgh | PERSON |  |
| 128 | Plot No.34!,SurveyNo.997/8 Model Coleay,Near Deep Bungalow Chowk, Pune-411016 | ADDRESS |  |
| 128 | tininfo@nsdLco.in | EMAIL |  |
