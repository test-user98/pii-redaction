# PII eval report

pred: `/Users/jaisipani/Desktop/scale/out/7248a14208cdae3f/spans.csv`  
truth: `/Users/jaisipani/Desktop/scale/eval/ground_truth/rhp_pages.csv`  
pages: 1, 2, 3, 4, 5, 6, 110, 111, 112, 114, 115, 116, 128

## Per type

| type | TP | FP | FN | precision | recall | F1 |
|---|---|---|---|---|---|---|
| ADDRESS | 22 | 7 | 6 | 0.759 | 0.786 | 0.772 |
| DIN | 8 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| DOB | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| EMAIL | 30 | 2 | 1 | 0.938 | 0.968 | 0.952 |
| ORG | 40 | 10 | 14 | 0.800 | 0.741 | 0.769 |
| PAN | 1 | 1 | 0 | 0.500 | 1.000 | 0.667 |
| PERSON | 54 | 3 | 1 | 0.947 | 0.982 | 0.964 |
| PHONE | 20 | 1 | 1 | 0.952 | 0.952 | 0.952 |
| **micro** | 176 | 24 | 23 | 0.880 | 0.884 | 0.882 |

Token accuracy: **0.9392** (4989/5312 tokens); pages without extractable text skipped: [128]

## Misses (FN)

| page | text | type | reason |
|---|---|---|---|
| 1 | KSH INTERNATIONAL LIMITED | ORG |  |
| 1 | 11/3, 11/4 and 11/5 Village Birdewadi Chakan Taluka - Khed Pune – 410 501 Maharashtra, India | ADDRESS |  |
| 5 | 201, Tower 2, Montreal Business Centre, Off Pallod Farms, Baner, Pune – 411 045, Maharashtra, India | ADDRESS |  |
| 6 | MUFG Intime India Private Limited | ORG |  |
| 6 | Link Intime India Private Limited | ORG |  |
| 110 | KSH International Limited | ORG |  |
| 110 | KSH International Limited | ORG |  |
| 110 | 12 Buena Monte, NCL co-operative housing society, Panchvati, Pashan, Pune – 411 008, Maharashtra, India | ADDRESS |  |
| 110 | Pratik Bunglow, Senapati Bapat Road, behind Sahara Hotel, Shivajinagar, Model Colony, Pune – 411 016, Maharashtra, India | ADDRESS |  |
| 112 | Nuvama Wealth Management Limited | ORG |  |
| 114 | I-Sec | ORG |  |
| 114 | Nuvama Wealth Management Limited | ORG |  |
| 114 | ICICI Venture House | ADDRESS |  |
| 115 | Abhijit Diwan | PERSON |  |
| 116 | Trilegal | ORG |  |
| 116 | MUFG Intime India Private Limited | ORG |  |
| 116 | Link Intime India Private Limited | ORG |  |
| 116 | HDFC Bank Limited | ORG |  |
| 116 | HDFC Bank Limited | ORG |  |
| 116 | ICICI Bank Limited | ORG |  |
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
| 110 |  Our Company is registered with the Registrar of Companies, Maharashtra at Pune, which is situated at the following address: Registrar of Companies, Maharashtra at Pune PCNTDA Green Building Block A 1st and 2nd floor Near Akurdi Railway Station Akurdi, Pune – 411 044 Maharashtra, India | ADDRESS |  |
| 110 | Managing Director | ADDRESS |  |
| 110 | 12 Buena Monte, NCL co-operative housing society, Panchvati, Pashan, Pune – 411 008, Maharashtra, India | ORG |  |
| 110 | Independent Director | ADDRESS |  |
| 110 | Pratik Bunglow, Senapati Bapat Road, behind Sahara Hotel, Shivajinagar, Model Colony, Pune – 411 016, Maharashtra, India | ORG |  |
| 110 | Independent Director | ADDRESS |  |
| 110 | Independent Director | ADDRESS |  |
| 112 | ICICI Venture House | ORG |  |
| 112 | Appasaheb Marathe | PERSON |  |
| 114 | ICICI Venture House | ORG |  |
| 128 | INCOMETAXDEPARTMENT GOVT.OFINDLA | ORG |  |
| 128 | /2000 & / Signature f HRG .341..997/8 ARCSR u-411016. If this card is lost/someone's lostcard is found please inform/return to: Income Tax PAN Services Unit,NSDL 4th Floor,Mantri Sterling. Plot No.34!,SurveyNo.997/8 Model Coleay,Near Deep Bungalow Chowk, Pune-411016 | ADDRESS |  |
| 128 | tininfo@nsdLco.in | EMAIL |  |
| 128 | INCOMETAXDEPARTMENT GOVT.OFINDLA | ORG |  |
| 128 | NBWPS1951N | PAN |  |
| 128 | VISHALSINGH | PERSON |  |
| 128 | SUGRIV SINGH Visha Simgh 06072020 | PERSON |  |
| 128 |  elT&R /Signature f HRG .341..997/8， ARCR u-411016. Ifthis card is lost / someone's lostcard is found please inform/return to: Income Tax PAN Services Unit,NSDL 4th Floor,Mantri Sterling. Plot No.34!,Survey No.997/8 Model Coleay,Near Deep Bungalow Chowk, Pune-411016 | ADDRESS |  |
| 128 | 20-27218080 | PHONE |  |
| 128 | tininfo@nsdLco.in | EMAIL |  |
