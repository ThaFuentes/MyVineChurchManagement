# Adding a sermon to the library from a Google Drive link

How the public message library at `/sermons/` gets a new message, and what to do when a
sermon is sitting on Google Drive as a link.

Written 2026-11-14. Matches `app/utils/sermon_drive.py` and `app/routes/sermons/drive_pages.py`.

## 1. How the library works

The library is a **mirror of one or more Google Drive folders**. It keeps the title, speaker,
date, and the Drive file id; the audio and video stay on Drive.

- Table: `sermon_drive_items` (one row per Drive file), folders in `sermon_drive_sources`.
- The site reads the folder listing (`embeddedfolderview`), parses each file name, and writes
  title / speaker / date / series / note.
- Playback never downloads the file. The page embeds
  `https://drive.google.com/file/d/<file id>/preview` in an iframe. `/sermons*` adds
  `frame-src https://drive.google.com https://docs.google.com` to the CSP for that page only.
- A saved copy is optional and never shown on the page: Staff, Admin, Owner, or a member
  granted `upload_sermons` / `moderate_sermons` can store one file per click outside the web
  root (`GET, POST /sermons/library/<id>/copy`). The site serves it only after Drive no longer
  has the file (`missing_on_drive=1`).

So "adding a sermon by URL" means **making the file visible in the folder the site reads**,
or **pointing the site at a folder URL**. There is no single-file import from a Drive link yet
(see §6).

## 2. Fastest path: one file, one folder

1. Put the audio in the Drive folder the site already reads.
2. Share it so anyone with the link can view (the site reads the folder anonymously).
3. Name the file so it parses (see §3).
4. Sign in as Staff, Admin, or Owner and open `/sermons/`. The refresh button is on that
   page; the folder forms are at Settings → Messages (`/settings/messages`). If neither is
   there, POST the route (§4) or wait for the scheduled check.

New files are inserted on the next sync. The file name decides the fields on first sight.

## 3. File naming that parses

Split fields with ` - ` (space, hyphen, space). The first part that looks like a date becomes
the date; the first part that looks like a person name becomes the speaker; everything left
becomes the title.

```
2026-11-08 - Josh Villasenor - Hope That Holds.m4a
2026-11-08 - Josh Villasenor - Hope That Holds (Romans 5:1-5).m4a
Faith That Works - Message - 2026-11-08 - Josh Villasenor - Hope That Holds.m4a
```

- **Date** must be exactly `YYYY-MM-DD` as its own part.
- **Speaker** must be 2–4 words, each starting with a capital letter (`Joshua V` works).
  `Name and Name` is accepted; a topic after `and` stays in the title. This is the file-name
  rule only — a name typed on the edit form (§5) is not limited this way, and the speaker does
  **not** have to be a member: `Tim Lien` is the pastor and has no account.
- **Note**: text in the last `(parentheses)` becomes the summary/description.
- **Series**: prefix `Series - Message - ...` (the word `Message` must be the second part).
- **Extensions mirrored**: `mp3 m4a wav aac ogg mp4 webm mov mkv`. Anything else is ignored.
- A name that does not parse still creates a row — with the file name as the title and no
  speaker or date. `VFC 11-8-26.m4a` is an example: no `YYYY-MM-DD` part, no name part, so
  it lands as title `VFC 11-8-26`. Fix it once on the edit form (§5); the site then keeps
  your edit and a later Drive rename will not overwrite it (`site_edited`).

Limits per sync: 2 folder levels deep, 8 folders, 400 files.

## 4. URLs and routes that exist today

All of these are HTML form posts on the sermons blueprint (`/sermons`), session login, CSRF
token required. They are not the bot API. The folder, schedule, and privacy forms live on the
Settings → Messages page (`/settings/messages`); the refresh button is on `/sermons/`; the
speaker page is `/sermons/library/speakers`.

| What | Route | Who | Form fields |
|---|---|---|---|
| Add or rename a Drive folder | `POST /sermons/library/source` | Owner | `folder` (folder link or bare id), `label` (optional, 120 chars) |
| Enable / rename an existing folder | `POST /sermons/library/source-update` | Owner | `source_id`, `label` (required, 120 chars), `enabled` = `1` / `0` (`0` hides the folder and its messages) |
| Read every folder now | `POST /sermons/library/refresh` | Staff, Admin, Owner | none |
| How often Drive is read | `POST /sermons/library/schedule` | Staff, Admin, Owner | `refresh_hours` = `168`, `24`, `8`, or `0` (staff-only refresh) |
| Default privacy for new items | `POST /sermons/library/default-visibility` | Staff, Admin, Owner (privacy permission) | `visibility` |
| Privacy for every item | `POST /sermons/library/visibility-all` | same | `visibility` |
| Add a speaker name (no account needed) | `POST /sermons/library/speakers/add` | Staff, Admin, Owner | `speaker` |
| Link / combine speakers | `GET, POST /sermons/library/speakers` | Staff, Admin, Owner | `action` = `create`, `add_name`, `link`, `unlink`, `combine`, `listen_rule` |
| Edit one message | `GET, POST /sermons/library/<id>/edit` | Staff, Admin, Owner | §5 |
| One message page | `GET /sermons/library/<id>` | depends on `visibility` | — |

Folder URL accepted by `extract_folder_id`: a bare id (`[A-Za-z0-9_-]{10,128}`), a
`drive.google.com/drive/folders/<id>` link, or an `embeddedfolderview...?id=<id>` link. An
`open?id=<id>` link is **not** accepted, and neither is a **file** link (`/file/d/<id>/view`)
— this is the folder picker, not a file import.

## 5. Editing the fields the file name got wrong

`/sermons/library/<id>/edit` (or the Edit button on the message page when signed in as staff):

- `title` — required, 255 chars.
- `preached_on` — `YYYY-MM-DD` or blank.
- `speaker` — free text (160). An account is never required: the name is saved as a speaker
  row with `user_id` empty, so preachers who are not members (e.g. `Tim Lien`) work exactly
  like members.
- `speaker_id` — pick a saved speaker instead of typing. Typing a name that is already saved
  (same letters, any case) reuses that speaker — it does not create a duplicate — and its
  saved spellings and listen rule stay. If you give the same name to a *different* speaker,
  the site refuses and points you at Speakers to combine them.
- `speaker_user` — optional. Link that speaker to a member account. The linked member can
  then set who listens for every message under that name; leaving it blank costs nothing.
- `scripture` (255), `series` (160), `summary` (4000, newlines kept).
- `visibility` — `public` (Anyone), `members` (signed-in members), `leaders` (Admin/Owner).
- `hidden` — `1` hides it from the library without deleting it.
- `visibility` and `hidden` are only on the form for Owner, Admin, someone granted the sermon
  privacy permission, or the member the message is assigned to. For anyone else the server
  keeps the old values and saves only the other fields.

Saving sets `site_edited=1`. From then on a Drive rename updates only the file metadata
(and the playback id), never your title/speaker/date.

The Drive file id itself is **not** editable on this form. An item belongs to the file it was
synced from (`drive_file_id` is unique). To change the audio, upload a new **version** of the
same Drive file: the id stays, so the row, its comments, and its reactions stay. A different
file with the same name is a new id and a new row — the old row then goes `missing_on_drive`
and staff-only. Either way a site-edited row keeps its title, speaker, and date.

## 6. Bot API / single-link import — not built

Checked 2026-11-14. There is **no** endpoint that takes one Drive file URL and creates one
library item.

- `GET /api/bot/read/sermons` reads the `sermons` table (the staff uploads page), not
  `sermon_drive_items`. It returns no library rows.
- `POST /api/bot/sermons` builds pastoral sermon drafts. There `preacher` must resolve to a
  `users` row (`bot_sermon_common._person`), it has no `guest_name` field, and there is no
  Drive attach. That is this endpoint's own rule — not a rule of the sermon library or of
  who may be a speaker.
- `POST /api/bot/lineup` is the bot route that already handles non-members: `guest_name`
  (191 chars) puts someone with no account on the speaking role, and a member wins over a
  guest name when both are sent (`assignments_with_speaker`). That is how a pastor who never
  signs in gets tagged for a service.
- `POST /api/bot/upload` is pictures/video for other places, no audio, no library place.
- Nothing under `/api/bot/` touches `sermon_drive_items`.

The contract to implement (auth, switches, audit and rate limits the same as the other bot
routes; refuse unknown fields) is in `FREEBUFF_SERMON_LIBRARY.md` §C:

```
GET   /api/bot/sermons/library?speaker=&from=&to=
GET   /api/bot/sermons/library/<id>
POST  /api/bot/sermons/library   {title, speaker (name) | speaker_id, date, campus?,
                                  folder?, drive_url|drive_id, description?,
                                  published?}   # speaker name, account optional
PATCH /api/bot/sermons/library/<id>
GET|POST /api/bot/sermons/speakers
```

**Speakers are names, not accounts — do not change this.** A library item must be addable with
just a name, reusing a person who already exists. `Tim Lien` preaches and is not a member:
`sermon_speakers` has `user_id NULL` for him, and `sermon_speaker_names` holds every spelling
that folds to him. So the endpoint must:

1. Fold the incoming name with `speaker_key` (case/space-insensitive) and look it up in
   `sermon_speaker_names.name_key`.
2. If it matches, attach that `speaker_id` and use that speaker's display name and listen rule.
   This is what sync already does (`_attach_known_speakers`).
3. If it does not match, create `sermon_speakers (display_name, user_id=NULL)` plus its
   `sermon_speaker_names` row — the same result as `create_speaker(name)` on the Speakers page.
4. Never require a `users` row, and never invent one for a walk-in preacher. Linking an
   account (`speaker_user`) is a separate, optional step.

The one place an account is genuinely required is `visibility=members` / `leaders` — that
limits *listeners*, not the speaker.

Until that exists, the API path for a new message is: add it to the folder (Drive API or the
Drive UI), then `POST /sermons/library/refresh` as staff.

## 7. Worked example: 2026-11-08, Josh Villasenor

Drive file: `VFC 11-8-26.m4a`, id `1IBlvrocxD0lpGDl39t_n33bq93KgbFTr`.

1. Move or copy the file into the folder set at `/sermons/library/source`, renamed to
   `2026-11-08 - Josh Villasenor - <Sermon title>.m4a`.
2. Share it as "anyone with the link can view".
3. As staff, `POST /sermons/library/refresh` → flash reports the message count.
4. Open `/sermons/?who=josh+villasenor` (the folded full name) and check the new row. A `who`
   value that is not an exact saved name is dropped, so `who=josh` finds nothing.
5. Open the message page: the Drive player should embed. If it says the content is blocked,
   the file is not shared publicly — the CSP is already right (`with_drive_frame`).

If the file keeps its original name, step 1 is skipped and the row appears as
`VFC 11-8-26` with no speaker and no date; fix it on the edit form (§5).

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| New file never appears | Not in the folder being read, extension not in the list, deeper than 2 levels, or folder not shared publicly. `POST /sermons/library/refresh` and read the flash. |
| "The library is already refreshing" | `sermon_drive_sync.lock` is held by a running sync; reload in a moment. |
| Player says content is blocked | Drive sharing, not the site. Set "anyone with the link can view". |
| Title reverts after a Drive rename | Expected only if the row was never edited (`site_edited=0`). |
| Item missing after a sync | The file left the folder: `missing_on_drive=1`. Put it back, or it stays playable only from a saved server copy. |
| Speaker not selectable | Add it at `POST /sermons/library/speakers/add` (guests need no account), then pick it on the edit form. |

## 9. Code map

| Concern | File |
|---|---|
| Folder walk, name parsing, upsert plan, reads | `app/utils/sermon_drive.py` |
| Routes and permissions above | `app/routes/sermons/drive_pages.py` |
| Tables / seed | `app/builddb/sermon_drive.py` |
| Pages | `app/templates/sermons/library.html`, `public/sermons/library.html`, `sermons/library_edit.html` |
| Bot API gaps and contract | `FREEBUFF_SERMON_LIBRARY.md` |

## Rules for changing this area

- Migrations additive; back up the DB first.
- Do not put the folder id, file id, or a saved-copy path in a page.
- No commit, push, or deploy without the operator's OK; log changes in `SERVER_CHANGES.md`.
