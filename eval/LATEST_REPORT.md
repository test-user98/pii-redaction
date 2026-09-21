# PII eval report

pred: `/Users/jaisipani/Desktop/scale/out/7248a14208cdae3f/spans.csv`  
truth: `/Users/jaisipani/Desktop/scale/eval/ground_truth/rhp_pages.csv`  
pages: 1, 2, 3, 4, 5, 6, 110, 111, 112, 114, 115, 116, 128

## Per type

| type | TP | FP | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|
| ADDRESS | 26 | 3 | 2 | 0.897 | 0.929 | 0.912 |
| DIN | 8 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| DOB | 1 | 1 | 0 | 0.500 | 1.000 | 0.667 |
| EMAIL | 30 | 2 | 1 | 0.938 | 0.968 | 0.952 |
| ORG | 51 | 9 | 3 | 0.850 | 0.944 | 0.895 |
| PAN | 1 | 1 | 0 | 0.500 | 1.000 | 0.667 |
| PERSON | 54 | 3 | 1 | 0.947 | 0.982 | 0.964 |
| PHONE | 20 | 1 | 1 | 0.952 | 0.952 | 0.952 |
| **micro** | 191 | 20 | 8 | 0.905 | 0.960 | 0.932 |

Token accuracy: **0.9782** (5196/5312 tokens); pages without extractable text skipped: [128]

## Misses (FN)

| page | text | type | reason |
|---|---|---|---|
| 6 | Link Intime India Private Limited | ORG |  |
| 114 | ICICI Venture House | ADDRESS |  |
| 115 | Abhijit Diwan | PERSON |  |
| 116 | Link Intime India Private Limited | ORG |  |
| 116 | HDFC Bank Limited | ORG |  |
| 128 | 4th Floor, Mantri Sterling, Plot No. 341, Survey No. 997/8, Model Colony, Near Deep Bungalow Chowk, Pune - 411 016 | ADDRESS |  |
| 128 | 91-20-2721 8081 | PHONE |  |
| 128 | tininfo@nsdl.co.in | EMAIL |  |

## False hits (FP)

| page | text | type | reason |
|---|---|---|---|
| 3 | PromoterSellingShareholder | ORG |  |
| 4 | nuvama iICICI Securities | ORG |  |
| 5 | FINANCIAL EXPRESS | ORG |  |
| 5 | nuvama iICICI Securities G | ORG |  |
| 6 | ICICI Venture House | ORG |  |
| 110 | PCNTDA Green Building Block A 1st and 2nd floor Near Akurdi Railway Station Akurdi, Pune – 411 044 Maharashtra, India | ADDRESS |  |
| 112 | ICICI Venture House | ORG |  |
| 112 | Appasaheb Marathe | PERSON |  |
| 114 | ICICI Venture House | ORG |  |
| 128 | INCOMETAXDEPARTMENT GOVT.OFINDLA | ORG |  |
| 128 | NSDL 4th Floor,Mantri Sterling. Plot No.34!,SurveyNo.997/8 Model Coleay,Near Deep Bungalow Chowk, Pune-411016 | ADDRESS |  |
| 128 | tininfo@nsdLco.in | EMAIL |  |
| 128 | INCOMETAXDEPARTMENT GOVT.OFINDLA | ORG |  |
| 128 | NBWPS1951N | PAN |  |
| 128 | VISHALSINGH | PERSON |  |
| 128 | SUGRIV SINGH Visha Simgh 06072020 | PERSON |  |
| 128 | 06/05/2000 | DOB |  |
| 128 | Plot No.34!,Survey No.997/8 Model Coleay,Near Deep Bungalow Chowk, Pune-411016 | ADDRESS |  |
| 128 | 20-27218080 | PHONE |  |
| 128 | tininfo@nsdLco.in | EMAIL |  |
