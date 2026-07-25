# Leisure time-use: primary sources (US / JP / DE)

Research date: 2026-07-25. Purpose: ground the leisure profile tables at
`backend/app/data/leisure/{us,jp,de}.csv` — participation rates and time spent per
harmonized category, from national time-use surveys.

The research was commissioned for a hobby-bank weighting scheme that 006i
replaced; §2's named-activity rates are kept because they are the data a v2
named-activity layer would use, per country, where such a survey exists.

Metric vocabulary used below:

- **min/day (population)** — average minutes per day across the whole population,
  including non-participants. Good for envelope shares.
- **participation rate (diary day)** — % of people who did the activity on the diary
  day (ATUS, HETUS). Good for within-category splits of frequent activities.
- **participation rate (past year)** — % who did the activity at least once in the past
  year (Japan 行動者率). Best available signal for "is this a hobby of yours" — closest
  to what a persona interest list means.

---

## 1. Category envelope shares (leisure only, normalized)

### United States — BLS ATUS 2024 (Table A-1)

Source: American Time Use Survey, 2024 annual averages, persons 15+.
Table A-1 "Time spent in detailed primary activities and percent of the civilian
population engaging in each activity, averages per day by sex".
URL: https://www.bls.gov/tus/tables/a1-2024.pdf (BLS blocks non-browser clients;
mirror that works from scripts: https://web.archive.org/web/2026/https://www.bls.gov/tus/tables/a1-2024.pdf)

Leisure and sports total: **5.07 h/day** (94.1% engaged on diary day).

| Sub-category | h/day | share of leisure | participation rate (diary day) |
|---|---|---|---|
| Watching TV | 2.60 | 51.3% | 72.8% |
| Socializing and communicating | 0.59 | 11.6% | 29.9% |
| Playing games | 0.37 | 7.3% | 15.3% |
| Relaxing and thinking | 0.36 | 7.1% | 20.6% |
| Sports, exercise, recreation | 0.34 | 6.7% | 22.1% |
| Reading for personal interest | 0.28 | 5.5% | 16.1% |
| Computer use for leisure (excl. games) | 0.20 | 3.9% | 13.0% |
| Arts and entertainment (other than sports) | 0.05 | 1.0% | 2.2% |
| Travel related to leisure and sports | 0.17 | 3.4% | 25.6% |

Adjacent (classified under "Household activities", relevant to the banks):
lawn & garden care 0.20 h/day, 9.9% diary-day participation; animals & pets 0.15 h/day,
20.1%.

### Japan — 社会生活基本調査 2021 (Statistics Bureau), 調査票A, 生活時間編

Source: 令和3年社会生活基本調査 結果の概要 (Table 1-1, weekly average, persons 10+),
PDF: https://www.stat.go.jp/data/shakai/2021/pdf/gaiyoua.pdf (pp. 2–3).
Landing page: https://www.stat.go.jp/data/shakai/2021/kekka.html
Metric: **min/day (population, week average)** — participation rates per time-use
category are not in the summary PDF (they are in e-Stat detail tables).

3次活動 (free time) total 6 h 16 min. Leisure-relevant rows:

| Category (行動の種類) | h.min/day | share of leisure subset* |
|---|---|---|
| テレビ・ラジオ・新聞・雑誌 (TV/radio/print) | 2.08 | 40.5% |
| 休養・くつろぎ (rest & relaxing) | 1.57 | 37.0% |
| 趣味・娯楽 (hobbies & amusements) | 0.48 | 15.2% |
| スポーツ (sports) | 0.13 | 4.1% |
| 交際・付き合い (socializing) | 0.10 | 3.2% |
| 学習・自己啓発 (learning, non-school) | 0.13 | — |
| 移動 (non-commute travel) | 0.22 | — |

*Share of the 5 h 16 min TV+rest+hobby+sport+social subset. Gender: men 趣味・娯楽
1:00 vs women 0:37; TV men 2:11 vs women 2:05; sports men 0:16 vs women 0:10.

### Germany — Eurostat HETUS 2020 round = Destatis ZVE 2022 (`tus_20age`)

Source: Eurostat dataset **tus_20age** "Time spent in the main activity by sex and age
group", HETUS 2020 wave, geo=DE, time=2020 (Germany's underlying fieldwork is the
Destatis Zeitverwendungserhebung 2022). First published 2026-07-15. Units available:
TIME_SP (hh:mm, population), PTP_TIME (hh:mm among participants), **PTP_RT
(participation rate on diary day, %)**. 16 age bands from Y10-14 to Y_GE75.
Re-pull: `https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/tus_20age?format=JSON&geo=DE&lang=en`

Leisure total (AC4-8_998_X_713, excl. handicrafts): **5:54/day** (M 6:08, F 5:41).

| acl18 code | Activity | hh:mm | share | part. rate | M rate | F rate |
|---|---|---|---|---|---|---|
| AC821 | Watching TV, video or DVD | 2:07 | 35.9% | 73.5% | 73.3% | 73.7% |
| AC512_513_519 | Socialising with others | 0:39 | 11.0% | 29.5% | 27.5% | 31.5% |
| AC514-516 | Virtual social life | 0:23 | 6.5% | 37.1% | 30.0% | 43.9% |
| AC511 | Socialising with family | 0:06 | 1.7% | 12.2% | 11.9% | 12.6% |
| AC6_X_611 | Sports & outdoor (excl. walking) | 0:19 | 5.4% | 20.7% | 21.0% | 20.4% |
| AC611 | Walking and hiking | 0:15 | 4.2% | 16.3% | 14.9% | 17.6% |
| AC733-735 | Computer/console/mobile games | 0:17 | 4.8% | 12.8% | 16.8% | 9.0% |
| AC711_712_719_731_732_739 | Arts, hobbies, non-digital games | 0:16 | 4.5% | 15.3% | 14.2% | 16.4% |
| AC72 | Computing (leisure) | 0:14 | 4.0% | 20.1% | 23.1% | 17.2% |
| AC81_X_812 | Reading excl. books | 0:15 | 4.2% | 24.4% | 23.6% | 25.2% |
| AC812 | Reading books | 0:12 | 3.4% | 14.4% | 10.7% | 18.0% |
| AC52 | Entertainment and culture (going out) | 0:15 | 4.2% | 8.0% | 7.8% | 8.2% |
| AC4 | Voluntary work and meetings | 0:18 | 5.1% | 15.2% | 14.1% | 16.1% |
| AC531 | Resting — time out | 0:11 | 3.1% | 19.7% | 18.5% | 21.0% |
| AC831 | Listening to radio/recordings | 0:07 | 2.0% | 10.5% | 10.4% | 10.5% |

Adjacent (household chapter): AC34 gardening & pet care 0:21/day, 24.5% participation
(M 21.2%, F 27.7%).

### OECD Time Use Database (cross-check only)

SDMX dataflow: **OECD.WISE.INE / DSD_TIME_USE@DF_TIME_USE / 1.0**.
Re-pull: `https://sdmx.oecd.org/public/rest/data/OECD.WISE.INE,DSD_TIME_USE@DF_TIME_USE,1.0/all?format=csvfilewithlabels`

The currently served flow has only **5 top-level measures** (PAW, UPW, PCA, LEI, OTH)
by sex — no leisure sub-categories and no survey-year dimension. Total leisure,
min/day (population), sex = total:

| Country | Leisure min/day | M | F | underlying survey (per OECD notes) |
|---|---|---|---|---|
| USA | 279.9 | 304.9 | 255.1 | ATUS 2024 |
| DEU | 340.9 | 358.0 | 324.5 | ZVE 2022 |
| JPN | 269.0 | 284.0 | 254.0 | STULA 2021 |

Useful as a harmonized cross-country leisure envelope; use the national sources above
for sub-splits.

---

## 2. Japan: named-activity participation rates (行動者率, past year) — 2021

The entry-level jackpot. Persons 10+, activity done at least once Oct 2020–Oct 2021.
Source: 結果の概要 pp. 24–30 (tables 3-1, 3-3, 4-1, 4-3, 5-1; gender from fig. 4-2,
cross-checked against totals). Full detail (by age, prefecture, income) is on e-Stat:
survey code **00200533**, tstat **000001158160** (e.g. table 93-2 男女,趣味・娯楽の
種類別行動者率, stat_infid 000032223421).

Headline envelopes: スポーツ overall 66.5% (M 69.9 / F 63.3); 趣味・娯楽 overall
86.3% (M 86.8 / F 85.8); 旅行・行楽 (travel & excursions) 49.5% (M 48.9 / F 50.1 —
COVID-depressed, was 73.5% in 2016).

### Sports (only kinds with total rate ≥ 3.5% are published in the summary)

| Activity | 2021 rate | 2016 rate |
|---|---|---|
| ウォーキング・軽い体操 (walking / light exercise) | 44.3% | 41.3% |
| 器具を使ったトレーニング (gym equipment training) | 12.9% | 14.7% |
| ジョギング・マラソン (jogging / running) | 11.1% | 12.1% |
| サイクリング (cycling) | 8.2% | 7.9% |
| つり (fishing) | 7.8% | 8.7% |
| 登山・ハイキング (mountain climbing / hiking) | 7.7% | 10.0% |
| ゴルフ (golf) | 6.9% | 7.9% |
| 野球 (baseball) | 6.3% | 7.2% |
| バドミントン (badminton) | 6.1% | 6.7% |
| 水泳 (swimming) | 5.7% | 11.0% |
| ヨガ (yoga) | 5.5% | n/a |
| ボウリング (bowling) | 5.1% | 12.7% |
| 卓球 (table tennis) | 4.9% | 6.8% |
| サッカー (soccer) | 4.7% | 6.0% |
| バスケットボール (basketball) | 3.6% | 4.3% |
| バレーボール (volleyball) | 3.5% | 4.5% |

Women outrank men only in walking/light exercise, badminton, yoga.

### Hobbies & amusements (total rate ≥ 5%), with gender split

| Activity | Total | Men | Women |
|---|---|---|---|
| 音楽鑑賞 CD/スマホ (listening to music) | 53.5% | 53.3% | 53.7% |
| 映画鑑賞・映画館以外 (movies at home / streaming) | 52.7% | 53.0% | 52.4% |
| ゲーム スマホ・家庭用 (video/mobile games) | 42.9% | 46.6% | 39.3% |
| マンガを読む (reading manga) | 36.8% | 40.1% | 33.7% |
| 趣味としての読書 (reading, excl. manga) | 31.6% | 28.7% | 34.4% |
| 映画館での映画鑑賞 (cinema) | 29.8% | 28.8% | 30.8% |
| 園芸・庭いじり・ガーデニング (gardening) | 26.0% | 20.3% | 31.4% |
| 写真の撮影・プリント (photography) | 21.9% | 18.9% | 24.7% |
| 趣味としての料理・菓子作り (cooking / baking as hobby) | 19.0% | 9.0% | 28.5% |
| 遊園地・動植物園・水族館など (theme parks, zoos, aquaria) | 19.0% | 17.0% | 20.8% |
| スポーツ観覧・観戦・現地 (watching sports in person) | 14.5% | 18.2% | 11.0% |
| カラオケ (karaoke) | 13.5% | 13.3% | 13.8% |
| 美術鑑賞・現地 (art museums) | 11.4% | 9.8% | 12.9% |
| 日曜大工 (DIY / home carpentry) | 11.0% | 17.4% | 4.8% |
| 楽器の演奏 (playing an instrument) | 10.2% | 8.4% | 11.9% |
| 編み物・手芸 (knitting / handicrafts) | 8.8% | 0.8% | 16.5% |
| 演芸・演劇・舞踊鑑賞・現地 (live theater / dance) | 6.7% | 4.9% | 8.4% |
| パチンコ (pachinko) | 6.3% | 10.3% | 2.5% |
| キャンプ (camping) | 6.0% | 7.3% | 4.8% |
| ポピュラー音楽コンサート (pop concerts) | 5.9% | 4.5% | 7.2% |
| 和裁・洋裁 (sewing) | 5.5% | 0.7% | 10.1% |

Below-5% activities (shogi/go, bonsai, ceramics, etc.) exist in the e-Stat detail
tables (same tstat), not in the summary PDF.

Notable 2016→2021 swings (COVID-era; treat 2021 levels for karaoke, travel, live
events, bowling, swimming as depressed): karaoke −17.2 pts, theme parks −14.8,
cinema −9.8, live sports −7.0, bowling −7.6, games +7.1.

---

## 3. US: detailed-activity data beyond the leisure table (ATUS A-1, 2024)

Participation rates (diary day) already listed in §1. Additional bank-relevant rows
from the same table: attending sporting/recreational events 1.0%; attending or hosting
social events 1.7%; walking (as exercise) 8.2%; religious services 3.7%; volunteering
4.7%. Hunting/fishing, individual sports, and arts/crafts detail are NOT in A-1 —
they live in the ATUS microdata activity codes (e.g. 130104 fishing, 130106 hunting)
and would need the multi-year tables or microdata at https://www.bls.gov/tus/data.htm.
For yearly-participation style rates (comparable to Japan's 行動者率), the best free
US primary sources are the NEA Survey of Public Participation in the Arts (SPPA,
Census-run) and USFWS National Survey of Fishing, Hunting & Wildlife-Associated
Recreation — not pulled here.

---

## 4. Germany: entry-level numbers

### DOSB Bestandserhebung 2024 (sports-club memberships, reference date 2024-01-01)

Primary source for the sports-doing split. Total: 28,764,951 memberships in ~86,000
clubs (~34% of population; memberships, not unique persons).
PDF: https://cdn.dosb.de/user_upload/www.dosb.de/Medien_Service/BE/DOSB-Bestandserhebung_2024.pdf (p. 16, "Rangliste 2024 aller Spitzenverbände")

Top federations (memberships): Fußball 7,707,207; Turnen (gymnastics/fitness)
5,063,572; Tennis 1,491,386; Alpenverein (hiking/climbing) 1,472,311; Schützen
(shooting) 1,337,840; Leichtathletik 792,765; Handball 765,368; Golf 682,126;
Reiten (equestrian) 662,926; DLRG 606,317; Schwimmen 588,438; Tischtennis 527,300;
Ski 515,311; Volleyball 436,348; Basketball 274,025; Tanzsport 218,315; Segeln
193,740; Badminton 174,637; Radsport 150,305; Karate 144,583; Judo 132,088; Kanu
129,054; Schach 94,811; Hockey 87,989; Rudern 86,746; Eishockey 25,860; Dart 19,793.

### Destatis ZVE 2022

Germany's national time-use survey (Zeitverwendungserhebung 2022) is the source
feeding Eurostat `tus_20age` above — use the Eurostat API as the machine-readable
access path. Destatis landing page: https://www.destatis.de/DE/Themen/Gesellschaft-Umwelt/Einkommen-Konsum-Lebensbedingungen/Zeitverwendung/_inhalt.html
No German named-hobby (past-year) participation survey is freely available at
STULA-level granularity; the closest free proxies are DOSB memberships (above) and
the HETUS diary-day participation rates in §1.

---

## 5. How to use for bank weights

- Category envelopes: use §1 shares per country — they differ meaningfully (TV/media
  is ~51% of US leisure but ~36% of German; Japan's 趣味・娯楽 block is small in
  minutes but near-universal in participation).
- Map survey categories → bank categories roughly: sports-doing ← ATUS "sports,
  exercise, recreation" / HETUS AC6+AC611 / JP スポーツ; sports-watching ← ATUS
  attending events + JP スポーツ観戦; TV/media ← watching TV + radio rows; games ←
  playing games / AC733-735 / JP ゲーム; crafts ← arts&crafts rows + JP 編み物・手芸,
  日曜大工; music ← JP 楽器演奏 + HETUS arts bundle; outdoor ← walking/hiking,
  camping, fishing, gardening rows; social ← socializing rows; reading; travel ← JP
  旅行・行楽 (with COVID caveat).
- Within-category splits: Japan is fully covered by §2 (use 2016 values to de-bias
  COVID-depressed entries like karaoke and travel). Germany sports-doing: DOSB
  membership proportions. US within-category: ATUS gives only coarse splits — draft
  the rest and mark provenance as "drafted".
- Prefer past-year participation (JP) over diary-day rates (US/DE) when choosing a
  weight metric per country — but do not mix metrics within one country's bank without
  normalizing to shares first.

## 6. Gaps

- **OECD**: the live SDMX flow (`DSD_TIME_USE@DF_TIME_USE`) no longer carries leisure
  sub-categories (TV, sports, socializing…) that the old stats.oecd.org extract had,
  and has no survey-year dimension; the dataset landing page (oecd.org) returns 403 to
  scripted fetches, so survey-year attribution is from its cached description
  (updated 2026-04-30: DEU 2022, USA 2024).
- **BLS**: bls.gov 403-blocks non-browser clients; the numbers above came via the
  Wayback Machine mirror of `a1-2024.pdf`. Scripted re-pulls should use the ATUS-2024
  microdata files or the archive.org mirror.
- **US entry-level**: no free primary table found for named-hobby yearly participation
  (fishing, hunting, specific sports); SPPA/USFWS surveys exist but were not extracted.
- **Japan**: summary PDF truncates at 3.5% (sports) / 5% (hobbies) participation;
  rarer entries (shogi, ceramics, bonsai) need the e-Stat detail tables (survey
  00200533, tstat 000001158160). 2021 rates carry heavy COVID distortion for social/
  travel/live-event activities.
- **Germany**: no free named-hobby past-year participation survey (the commercial
  AWA/VuMA allensbach panels are paywalled); DOSB counts memberships, not persons,
  and under-represent non-club activities (gym training, jogging, yoga).
- **Eurostat 2000/2010 round** (`tus_00age` etc.) exists but Germany's row there is
  the 2012/13 ZVE; superseded by `tus_20age` (pulled above), so it was not extracted.
