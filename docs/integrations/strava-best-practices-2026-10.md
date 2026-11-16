# Strava best practices: one activity per workout, from one uploader

**Issue:** #5371 (epic #4625), with #5370 (the gym half: [gym-workflow-2026-10.md](gym-workflow-2026-10.md)) · **Verified:** 2026-10-26, updated 2026-11-11 (§7) · **Owner act:** applied 2026-10-26 ~00:30Z (attended, Session CH)
**Status:** inventory done, recommendation applied in the apps, and the proof read (§5) came back as expected on 2026-11-08. §7 is the current page: the 90-day inventory, what the platform now handles itself, and the three things that still matter

Most of this is app settings, not platform code. The platform's part is the inventory, a read-side fold that already absorbs the echoes, and the proof read. **Never call the Strava API to answer a question here.** Its token refresh rotates the stored secret, which is a write. The stored raw rows already carry `device_name`, and that field names the uploader.

## 1. Who uploads to Strava (the inventory)

These are the distinct activities from 2026-07-27 to 2026-10-25, by uploader. They come from the raw day files `raw/matthew/strava/activities/YYYY/MM/YYYY-MM-DD.json` (rows under `{"raw": {"activities": [...]}}`), read-only and counted by `strava_id`, and they were re-read for this page:

| Uploader (`device_name`) | Activities | Types | Carries | The platform already has it from |
|---|---|---|---|---|
| WHOOP | 58 | 31 Walk, 23 WeightTraining, 3 Ride, 1 Golf | heart rate and zones on all 58; GPS on 1; `trainer: true` on 57 | WHOOP's own API (workout rows with zones) |
| Hevy | 39 | 34 WeightTraining, 5 Workout | heart rate and zones on 5, all of them from 2026-10-18, when Hevy's watch app arrived | Hevy's API. The readers that resolve a visit drop these as echoes; the Strava-activity counters do not (#5387) |
| Garmin epix | 17 | 17 Walk | GPS, distance, heart rate | ended 2026-10-17 (the watch replaced it) |
| Apple Watch Ultra 4 | 2 | 1 Ride (10-18), 1 Walk (10-24) | heart rate and zones; GPS on the walk | the HAE workouts export, since 2026-10-25 |

The pliability app does not appear: it writes to HealthKit only, never to Strava.

After the watch arrived (10-17), WHOOP sent 7 of its 8 Strava walks and all 3 of its rides with `trainer: true`. These were WHOOP auto-detecting the treadmill and bike blocks Hevy already logs, inside the gym. Strava's Health list showed the watch's 10-25 ride already ticked. That suggests Strava had matched it to WHOOP's copy and skipped it. This is an inference from the app screen, not an API read.

A gym day therefore produced up to four Strava activities for one visit. On 2026-10-25 that was Hevy's push of the whole session, two WHOOP WeightTraining pieces, and WHOOP's Ride over the bike block.

## 2. Which app uploads what (the recommendation)

| Activity | The one Strava uploader | Why |
|---|---|---|
| Outdoor walk, hike, ride | **the watch**, through Strava › Health › Automatic uploads | the device worn for the workout, with GPS and the watch's own heart-rate zones |
| Gym cardio block (bike, treadmill) | **the watch** (the Workout app), same path | the protocol's heart-rate recorder for cardio (#5370). The Hevy block stays the plan of record |
| Gym lift | **Hevy's push** (kept) | harmless to the readers that resolve a visit. They drop a Hevy-device activity as the Hevy session's echo (`common.activity_overlap.HEVY_DEVICE`; `training.workout_identity.is_hevy_echo` when the Hevy row is in hand), except that a push carrying its own heart rate over a session holding a lift is kept as the lift's heart-rate member, adding no part and no minute (#5390). The Strava-activity counters still count it beside the ride (#5387). That is a code defect, not a reason to turn the push off |
| Anything WHOOP detects | **nobody**: WHOOP stops sharing | WHOOP's own API already gives the platform its workouts and zones, and its Strava copies were the echoes |

**Connected apps.** None needs disconnecting. WHOOP stays connected so it can **import** from Strava, because WHOOP labels its strain from Strava activities. Only WHOOP's **share** direction goes off. Hevy stays connected for its push. Garmin's connection is moot since 10-17. If Garmin is still listed, disconnecting it removes a dormant uploader that could re-sync history (§4).

## 3. What the owner applied (2026-10-26 ~00:30Z, attended, one step at a time)

- **WHOOP app:** "Automatically share to Strava" switched **off**. "Import activities from Strava" kept **on**.
- **Strava app › Health settings:** "Automatic uploads" switched **on**. "Send to Health" left **off**. If it were on, Strava would write its activities back into HealthKit, and they would return to the platform through Health Auto Export as yet another echo.
- **Hevy:** the Strava push kept, for the reason in §2 (the readers that still count it are #5387).

The protocol itself, recording a gym block once, needed no app setting (#5370 §1).

## 4. Avoiding backdated re-syncs (the #5257 class)

#5257 found three Walks created in one batch around 2026-10-21. Each one restated an existing activity with its local clock shifted +9 h. The owner confirmed them as copies and deleted them on 2026-10-25. They raised `MissingActivityCount{Source=strava}` to 3 and held `ingest-reconciliation-strava` in alarm. The batch's uploader was never read, because the stored rows never held those activities and the API read would rotate the token. They appeared within days of the new watch and its Health connection. That is consistent with a history re-sync from a newly connected source, but it is an inference.

Practices that keep that class away:

1. **Do not bulk-import history.** When a connection is new or re-authorised, skip any "upload past activities" or "sync history" offer, whether it is Strava's Health picker, WHOOP's re-share or a Garmin re-sync. The platform already holds every past workout from its own source.
2. **Check the phone's clock and time zone before any manual upload.** Set both to automatic. A +9 h shift is what a UTC+2 clock writes for a Pacific workout. Strava keys the activity by `start_date_local`, and the platform keys its day row the same way.
3. **Do not toggle a connection off and on to "fix" a sync.** Re-authorising is the usual trigger for a history backfill.
4. **Delete a duplicate in Strava when you notice it, ideally the same day.** The platform's ingest refreshes only the trailing 3 days (`refresh_trailing_days`), and Strava deletes and edits older than that never reach the store (#4638). An old duplicate only shows up as a reconciliation gap, and then the alarm, not the store, carries it.
5. **Leave "Send to Health" off.** It closes the loop that would turn every Strava activity into a HealthKit workout.

## 5. The 7-day live proof (2026-10-26 → 2026-11-02)

What closes #5371's box 4 (`**Live proof:** <UTC instant> — <where>`), read after 2026-11-02:

| Read | Expected | Baseline, the 7 days before (10-19 → 10-25) |
|---|---|---|
| WHOOP-device Strava rows on a gym day | **0** from 2026-10-26 | 9 WHOOP rows across 5 gym days (8 of them `trainer: true`) |
| Watch-device Strava rows | present, one per watch workout the owner records | 1 (a Walk) |
| The seam's fold count: `duplicate_activity_count` summed over the window's day rows through `common.strava_read_seam.dedup_strava_day` | **lower, ideally 0** | 3 |
| `LifePlatform/IngestReconciliation::MissingActivityCount{Source=strava}` | **0** on every daily datapoint | 3.0 on 10-21 and 10-22, from the #5257 copies (deleted 10-25) |

**One command** (#5371, `scripts/strava_uploader_proof.py`): `python3 scripts/strava_uploader_proof.py --since 2026-10-26 --until 2026-11-02` prints every row below for the window and for the equal window before it, counts only. The steps below are what it does, for reading it or doing it by hand.

How to read it, read-only (no Strava API, no write):

- **Rows and the fold count.** For each date `D`, `aws s3 cp s3://matthew-life-platform/raw/matthew/strava/activities/YYYY/MM/D.json`. Count distinct `strava_id` by `device_name`, `sport_type` and `trainer`. Then hand each day's `{"activities": raw["activities"]}` to `dedup_strava_day` and sum `duplicate_activity_count`. The raw file carries a few numeric fields as strings, so cast them to float first; the DynamoDB writer normalises them. Report counts only, never a heart rate, distance or GPS field.
- **The metric.** `aws cloudwatch get-metric-statistics --namespace LifePlatform/IngestReconciliation --metric-name MissingActivityCount --dimensions Name=Source,Value=strava --start-time 2026-10-26T00:00:00Z --end-time 2026-11-03T00:00:00Z --period 86400 --statistics Maximum`. The reconcile leg runs daily at about 17:20Z inside `strava-data-ingestion`; never invoke it by hand, because it rotates the token.
- **A gym day** is a day with a Hevy session. If the owner has no gym day in the window, the first box cannot be read, and it stays open rather than reading as a pass.

Two things to look for that would change the recommendation:

- **The watch uploading what Hevy or pliability wrote into HealthKit.** If "Automatic uploads" turns out to upload every HealthKit workout, not only the watch's own, then a gym day would show a watch-device WeightTraining or Yoga row beside Hevy's push. The platform folds a WeightTraining row of that kind into Hevy's push in the seam (same sport, different device, inside it). But the Strava-activity counters on #5387 would count it again. If it shows up, untick those workouts in Strava's Health list and note it on #5371.
- **The 10-25 ride case recurring.** That is a watch workout ticked in Strava's Health list but never uploaded. It meant Strava had matched the workout to another uploader's copy. With WHOOP's share off there should be no copy to match. A missing watch row on a gym day would say otherwise.

## 6. What the platform does with the echoes regardless

The settings above reduce noise. They are not what keeps the numbers right. Every stored day before 2026-10-26 still holds WHOOP's copies, and an uploader can change behaviour in any app update. The read side stays the guarantee:

- **`common.strava_read_seam`** folds same-sport copies: a start within 15 minutes, or, across two devices, 80% containment. It runs on every reader of the partition.
- **`training.workout_identity`** folds every Strava, HealthKit and Whoop record into the Hevy session's parts and drops Hevy's own push as an echo (#5369), unless the push carries its own heart rate and the session holds a lift: then it is the lift's heart-rate member (#5390).
- **The readers that still count Strava activities directly** are the open defect, #5387. They are listed in the gym-workflow table, row 12.

## 7. Update 2026-11-11: the 90-day inventory, what the platform now handles, what still matters

Read-only, from the stored `strava` day rows (`device_name` × `sport_type`) and the vendor's own activity list. Window 2026-08-10 → 2026-11-08. Counts and dates only. Detail is in the 2026-11-08 comment on #5371.

| Uploader | Before the watch (to 10-16) | Watch arrives, WHOOP still sharing (10-17 → 10-25) | After the owner act (10-26 → 11-08) |
|---|---|---|---|
| Hevy | 34 (29 WeightTraining, 5 Workout) | 5 WeightTraining | 10 WeightTraining |
| WHOOP | 40 (23 Walk, 17 WeightTraining) | 16 (7 Walk, 6 WeightTraining, 3 Ride) | **0** |
| Garmin epix | 15 Walk | 1 Walk | 0 |
| Apple Watch Ultra 4 | n/a | 1 Ride, 1 Walk | 3 Ride, 10 Walk (6 indoor, 4 outdoor), 1 Yoga |
| pliability | 0 | 0 | **0** |

What the data says. pliability never reaches Strava: 11 pliability sessions and 7 Hevy-written strength workouts sit in HealthKit since 10-26 and none is in Strava, so "Automatic uploads" sends only workouts the watch recorded (observed, not documented). A gym visit now yields two Strava activities, Hevy's push of the lift plus one watch cardio block (3 Rides and 6 indoor Walks over 9 of 10 gym days), down from up to four.

### Uploader per activity type

| Activity | Uploader | In effect? |
|---|---|---|
| Walk (outdoor), hike, ride | the watch, Strava › Health › Automatic uploads | yes, 4 outdoor walks since 10-26 |
| Treadmill walk, gym bike | the watch's Workout app; the Hevy block stays the plan of record | yes, 9 of 10 gym days |
| Lifting | Hevy's push only | yes, 10 of 10 |
| Yoga, mobility (pliability) | nobody: it stays in HealthKit | yes, with no setting needed |
| Anything WHOOP detects | nobody: share stays off | yes, 0 since 10-26 |

Apps. Keep WHOOP connected (import on, share off), Hevy's push on, Strava Health "Automatic uploads" on and "Send to Health" off. Disconnect Garmin Connect if it is still listed: its last upload was 10-17 and a dormant uploader is the likeliest source of a history re-sync (inference). Connect nothing new, and accept no "import past activities" offer.

### What the platform now handles on its own (so the settings above are hygiene, not the safety net)

- **Every activity is stored (#5696, PR #5752).** The write-side 120-second drop is gone: 8 vendor activities in 90 days had never been stored. Duplicates are resolved at the read seam (`common.strava_read_seam`), and Hevy's own push now yields to a device recording that covers at least 80% of its interval, so a tie no longer keeps the echo.
- **Late manual entries are picked up (#5753, PR #5763).** Each ingest run lists the trailing 30 days by start time and stores any activity id it does not hold. A walk typed in two weeks late for 2026-10-06 is the case it was built for. Strava cannot be asked by upload time, so the 30-day window is the limit.
- **The brief no longer lists the watch's gym ride or treadmill walk as extra cardio (#5697).** It reads the Hevy session that already holds that block.
- **The vacation fund counts treadmill miles once (#5695, PR #5751).** The watch's indoor walk and Hevy's Treadmill set record the same block. The fund now joins them and counts the Hevy distance. Six gym days since 10-26 had been counted twice, 16.92 mi in all, until the fix.
- **Sessions, walking volume and zone-2 minutes** already resolve a visit through `training.workout_identity`, so a cardio block inside a Hevy session counts once (#5387).

### What still matters to the owner

1. **Do not use Strava's duplicate or Health pickers to re-upload an old workout.** A 2026-10-06 walk entered about two weeks late is the only out-of-order activity since the watch arrived. PR #5763 identifies it as a manual entry, so it is a real walk and not a copy (this corrects the earlier reading, in the 11-08 comment, that it was a +9 h shifted duplicate). It is stored by the one-day backfill approved on #5753, not by deleting it. If a backdated entry is ever a duplicate, delete it in Strava, and do so within 30 days, because only the last 3 days' edits and deletes are re-read routinely (#4638).
2. **End and delete an accidental watch workout the same day.** The 67-second watch Yoga of 2026-11-07 is counted as a session until it is deleted in Strava, and a delete older than 3 days no longer reaches the store.
3. **Leave WHOOP's share off and Send to Health off.** They are the two settings whose reversal brings the echoes back: 0 WHOOP uploads since 10-26 against 16 in the 9 days before. Everything else is covered by the platform.
