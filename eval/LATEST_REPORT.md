# PII eval report

pred: `/Users/jaisipani/Desktop/scale/out/7248a14208cdae3f/spans.csv`  
truth: `/Users/jaisipani/Desktop/scale/eval/ground_truth/rhp_pages.csv`  
pages: 1, 2, 3, 4, 5, 6, 110, 111, 112, 114, 115, 116, 128

## Per type

| type | TP | FP | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|
| ADDRESS | 22 | 3 | 6 | 0.880 | 0.786 | 0.830 |
| DIN | 7 | 0 | 1 | 1.000 | 0.875 | 0.933 |
| DOB | 1 | 1 | 0 | 0.500 | 1.000 | 0.667 |
| EMAIL | 30 | 2 | 1 | 0.938 | 0.968 | 0.952 |
| ORG | 50 | 10 | 4 | 0.833 | 0.926 | 0.877 |
| PAN | 1 | 1 | 0 | 0.500 | 1.000 | 0.667 |
| PERSON | 49 | 3 | 6 | 0.942 | 0.891 | 0.916 |
| PHONE | 20 | 1 | 1 | 0.952 | 0.952 | 0.952 |
| **micro** | 180 | 21 | 19 | 0.896 | 0.905 | 0.900 |

Token accuracy: **0.9710** (5158/5312 tokens); pages without extractable text skipped: [128]

## Misses (FN)

| page | text | type | reason |
|---|---|---|---|
| 1 | 201, Tower 2, Montreal Business Centre, Off Pallod Farms, Baner Pune – 411 045 Maharashtra, India | ADDRESS |  |
| 4 | Nuvama Wealth Management Limited | ORG |  |
| 4 | Lokesh Shah | PERSON |  |
| 4 | Soumavo Sarkar | PERSON |  |
| 6 | Abhijit Diwan | PERSON |  |
| 6 | Link Intime India Private Limited | ORG |  |
| 110 | 12 Buena Monte, NCL co-operative housing society, Panchvati, Pashan, Pune – 411 008, Maharashtra, India | ADDRESS |  |
| 110 | 602, Gopalkrupa Apartment, Bhonde colony, Prabhat Road, Erandawane, Pune – 411 004, Maharashtra, India | ADDRESS |  |
| 110 | A-259, JK Road, Minal Residency, Huzur, Govindpura, Bhopal – 462 023, Madhya Pradesh, India | ADDRESS |  |
| 111 | Indu Jacob | PERSON |  |
| 111 | 05293084 | DIN |  |
| 112 | Abhijit Diwan | PERSON |  |
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
| 4 | nuvama iICICI Securities | ORG |  |
| 5 | FINANCIAL EXPRESS | ORG |  |
| 5 | nuvama iICICI Securities G | ORG |  |
| 6 | ICICI Venture House | ORG |  |
| 110 | PCNTDA Green Building Block A 1st and 2nd floor Near Akurdi Railway Station Akurdi, Pune – 411 044 Maharashtra, India | ADDRESS |  |
| 112 | ICICI Venture House | ORG |  |
| 112 | Appasaheb Marathe | PERSON |  |
| 114 | ICICI Venture House | ORG |  |
| 128 | INCOMETAXDEPARTMENT GOVT.OFINDLA | ORG |  |
| 128 | Income Tax PAN Services Unit | ORG |  |
| 128 | 4th Floor,Mantri Sterling. Plot No.34!,SurveyNo.997/8 Model Coleay,Near Deep Bungalow Chowk, Pune-411016 | ADDRESS |  |
| 128 | tininfo@nsdLco.in | EMAIL |  |
| 128 | INCOMETAXDEPARTMENT GOVT.OFINDLA | ORG |  |
| 128 | NBWPS1951N | PAN |  |
| 128 | VISHALSINGH | PERSON |  |
| 128 | SUGRIV SINGH Visha Simgh 06072020 | PERSON |  |
| 128 | 06/05/2000 | DOB |  |
| 128 | Income Tax PAN Services Unit | ORG |  |
| 128 | Plot No.34!,Survey No.997/8 Model Coleay,Near Deep Bungalow Chowk, Pune-411016 | ADDRESS |  |
| 128 | 20-27218080 | PHONE |  |
| 128 | tininfo@nsdLco.in | EMAIL |  |
